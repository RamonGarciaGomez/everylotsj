"""@everylotSJ Mastodon bot — posts one San Jose address every 2 minutes.

Usage:
    python bot.py                  # pick the next unposted address and post it
    python bot.py --dry-run        # print the post without publishing
    python bot.py --id 12345       # force a specific row ID
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from typing import Optional

import requests
from dotenv import load_dotenv
from mastodon import Mastodon

DB_PATH = "lots.db"
STREET_VIEW_URL = "https://maps.googleapis.com/maps/api/streetview"
STREET_VIEW_METADATA_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"
USER_AGENT = "everylotSJ-bot/1.0 (https://github.com/RamonGarciaGomez/everylotsj)"

PLACE_TYPES = {
    "SF": ("🏡", "Single Family"),
    "MF": ("🏘️", "Multi-Family"),
    "BU": ("🏬", "Commercial / Business"),
    "MH": ("🚐", "Mobile Home"),
    "CO": ("🏢", "Condo"),
    "TR": ("🚉", "Transit / Transportation"),
}

ZIP_NEIGHBORHOODS = {
    "95002": "Alviso",
    "95008": "Campbell",
    "95101": "Downtown",
    "95110": "Downtown",
    "95111": "South San Jose",
    "95112": "East San Jose",
    "95113": "Downtown",
    "95116": "Mayfair",
    "95117": "West San Jose",
    "95118": "Cambrian",
    "95119": "South San Jose",
    "95120": "Almaden Valley",
    "95121": "East San Jose",
    "95122": "East San Jose",
    "95123": "Blossom Valley",
    "95124": "Willow Glen",
    "95125": "Willow Glen",
    "95126": "Rose Garden",
    "95127": "East Foothills",
    "95128": "West San Jose",
    "95129": "West San Jose",
    "95130": "West San Jose",
    "95131": "North San Jose",
    "95132": "Berryessa",
    "95133": "Berryessa",
    "95134": "North San Jose",
    "95135": "Evergreen",
    "95136": "South San Jose",
    "95138": "Silver Creek",
    "95139": "South San Jose",
    "95140": "Mount Hamilton",
    "95148": "East San Jose",
}


def load_credentials() -> dict:
    load_dotenv()
    return {
        "MASTODON_CLIENT_KEY": os.getenv("MASTODON_CLIENT_KEY"),
        "MASTODON_CLIENT_SECRET": os.getenv("MASTODON_CLIENT_SECRET"),
        "MASTODON_ACCESS_TOKEN": os.getenv("MASTODON_ACCESS_TOKEN"),
        "MASTODON_INSTANCE_URL": os.getenv("MASTODON_INSTANCE_URL", "https://mastodon.social"),
        "GOOGLE_API_KEY": os.getenv("GOOGLE_API_KEY"),
    }


def get_lot(conn: sqlite3.Connection, row_id: Optional[int] = None) -> Optional[sqlite3.Row]:
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    if row_id is not None:
        cur.execute("SELECT * FROM lots WHERE id = ?", (row_id,))
    else:
        cur.execute("SELECT * FROM lots WHERE posted = 0 ORDER BY id ASC LIMIT 1")
    return cur.fetchone()


def extract_zip(address: str) -> Optional[str]:
    m = re.search(r"\b(9\d{4})\b", address)
    return m.group(1) if m else None


def format_post(lot: sqlite3.Row) -> str:
    lines = []
    lines.append(f"📍 {lot['address']}")

    place = PLACE_TYPES.get(lot["place_type"] or "")
    if place:
        emoji, label = place
        lines.append(f"{emoji} Property type: {label}")

    lines.append("#SanJose #everylotSJ")
    return "\n".join(lines)


def format_bio(address: str) -> str:
    zipcode = extract_zip(address)
    neighborhood = ZIP_NEIGHBORHOODS.get(zipcode, "San Jose") if zipcode else "San Jose"
    location = f"{neighborhood} ({zipcode})" if zipcode else neighborhood
    return (
        f"Posting every address in San Jose one by one (all 394k) 📍\n"
        f"Currently in: {location}\n"
        f"Created by Ramón → ramongarciagomez.com"
    )


def street_view_has_image(lat: float, lon: float, api_key: str) -> bool:
    try:
        r = requests.get(
            STREET_VIEW_METADATA_URL,
            params={"location": f"{lat},{lon}", "key": api_key},
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
        return r.status_code == 200 and r.json().get("status") == "OK"
    except (requests.RequestException, ValueError):
        return False


def fetch_street_view(lat: float, lon: float, api_key: str) -> Optional[str]:
    if not street_view_has_image(lat, lon, api_key):
        print("  No Street View imagery available for this location.")
        return None
    try:
        r = requests.get(
            STREET_VIEW_URL,
            params={"size": "1200x675", "location": f"{lat},{lon}", "key": api_key},
            headers={"User-Agent": USER_AGENT},
            timeout=30,
        )
        if r.status_code != 200 or len(r.content) < 5000:
            print(f"  Street View fetch failed (status {r.status_code}).")
            return None
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp.write(r.content)
        tmp.close()
        return tmp.name
    except requests.RequestException as e:
        print(f"  Street View error: {e}")
        return None


def post_to_mastodon(text: str, image_path: Optional[str], address: str, creds: dict) -> tuple[Optional[str], Mastodon]:
    mastodon = Mastodon(
        client_id=creds["MASTODON_CLIENT_KEY"],
        client_secret=creds["MASTODON_CLIENT_SECRET"],
        access_token=creds["MASTODON_ACCESS_TOKEN"],
        api_base_url=creds["MASTODON_INSTANCE_URL"],
    )

    media_ids = None
    if image_path:
        print("  Uploading image...")
        alt_text = f"Google Street View image of {address}"
        media = mastodon.media_post(image_path, mime_type="image/jpeg", description=alt_text)
        media_ids = [media["id"]]

    print("  Posting to Mastodon...")
    status = mastodon.status_post(text, media_ids=media_ids, visibility="public")
    return str(status["id"]) if status else None, mastodon


def update_bio(mastodon: Mastodon, address: str) -> None:
    bio = format_bio(address)
    print(f"  Updating bio: {repr(bio)}")
    mastodon.account_update_credentials(note=bio)


def mark_posted(conn: sqlite3.Connection, lot_id: int, post_id: Optional[str]) -> None:
    conn.execute(
        "UPDATE lots SET posted = 1, post_id = ?, posted_at = ? WHERE id = ?",
        (post_id, datetime.now(timezone.utc).isoformat(), lot_id),
    )
    conn.commit()


def main():
    ap = argparse.ArgumentParser(description="@everylotSJ bot")
    ap.add_argument("--dry-run", action="store_true", help="Print post without publishing")
    ap.add_argument("--id", dest="row_id", type=int, default=None, help="Force a specific row ID")
    args = ap.parse_args()

    creds = load_credentials()

    if not os.path.exists(DB_PATH):
        print(f"ERROR: {DB_PATH} not found. Run `python setup_db.py` first.")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("BEGIN IMMEDIATE")
        lot = get_lot(conn, row_id=args.row_id)
        if lot is None:
            conn.rollback()
            msg = f"No lot found with ID {args.row_id}." if args.row_id else "No unposted lots remaining!"
            print(msg)
            sys.exit(0)

        print(f"Selected ID {lot['id']} — {lot['address']}")

        post_text = format_post(lot)
        bio_text = format_bio(lot["address"])
        print("---- post preview ----")
        print(post_text)
        print("---- bio preview ----")
        print(bio_text)
        print("----------------------")

        image_path = None
        if lot["lat"] is not None and lot["lon"] is not None and creds.get("GOOGLE_API_KEY"):
            print("  Fetching Street View image...")
            image_path = fetch_street_view(lot["lat"], lot["lon"], creds["GOOGLE_API_KEY"])
            if image_path:
                print(f"  Saved image: {image_path}")
        elif not creds.get("GOOGLE_API_KEY"):
            print("  (no GOOGLE_API_KEY — skipping Street View)")

        try:
            if args.dry_run:
                conn.rollback()
                print("[DRY RUN] Not posting.")
                if image_path:
                    print(f"[DRY RUN] Would attach image: {image_path}")
            else:
                missing = [k for k, v in creds.items() if k.startswith("MASTODON_") and not v]
                if missing:
                    conn.rollback()
                    print(f"ERROR: Missing Mastodon credentials: {missing}")
                    sys.exit(1)
                try:
                    post_id, mastodon = post_to_mastodon(post_text, image_path, lot["address"], creds)
                    mark_posted(conn, lot["id"], post_id)
                    print(f"Posted! Status ID: {post_id}")
                    update_bio(mastodon, lot["address"])
                except Exception as e:
                    conn.rollback()
                    print(f"Posting failed: {e}")
                    print("Address NOT marked as posted — will retry next run.")
                    sys.exit(1)
        finally:
            if image_path and os.path.exists(image_path):
                os.unlink(image_path)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
