"""@everylotSJ Twitter bot — posts one San Jose address per hour.

Usage:
    python bot.py                  # pick the next unposted address and tweet it
    python bot.py --dry-run        # print the tweet without posting
    python bot.py --id 12345       # force a specific row ID
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from typing import Optional

import requests
from dotenv import load_dotenv

DB_PATH = "lots.db"
STREET_VIEW_URL = "https://maps.googleapis.com/maps/api/streetview"
STREET_VIEW_METADATA_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"

PLACE_TYPE_LABELS = {
    "SF": "Single Family",
    "MF": "Multi-Family",
    "BU": "Commercial / Business",
    "MH": "Mobile Home",
    "CO": "Condo",
    "TR": "Transit / Transportation",
}


def load_credentials() -> dict:
    load_dotenv()
    return {
        "TWITTER_API_KEY": os.getenv("TWITTER_API_KEY"),
        "TWITTER_API_SECRET": os.getenv("TWITTER_API_SECRET"),
        "TWITTER_ACCESS_TOKEN": os.getenv("TWITTER_ACCESS_TOKEN"),
        "TWITTER_ACCESS_TOKEN_SECRET": os.getenv("TWITTER_ACCESS_TOKEN_SECRET"),
        "GOOGLE_API_KEY": os.getenv("GOOGLE_API_KEY"),
    }


def get_lot(conn: sqlite3.Connection, row_id: Optional[int] = None) -> Optional[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if row_id is not None:
        cur.execute("SELECT * FROM lots WHERE id = ?", (row_id,))
    else:
        cur.execute("SELECT * FROM lots WHERE posted = 0 ORDER BY id LIMIT 1")
    return cur.fetchone()


def format_tweet(lot: sqlite3.Row) -> str:
    lines = []
    lines.append(f"📍 {lot['address']}")

    label = PLACE_TYPE_LABELS.get(lot["place_type"] or "", "")
    if label:
        lines.append(f"🏠 Property type: {label}")

    lines.append("#SanJose #everylotSJ")
    return "\n".join(lines)


def street_view_has_image(lat: float, lon: float, api_key: str) -> bool:
    try:
        r = requests.get(
            STREET_VIEW_METADATA_URL,
            params={"location": f"{lat},{lon}", "key": api_key},
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
            timeout=30,
        )
        if r.status_code != 200 or len(r.content) < 5000:
            print(f"  Street View fetch failed or returned tiny image (status {r.status_code}).")
            return None
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp.write(r.content)
        tmp.close()
        return tmp.name
    except requests.RequestException as e:
        print(f"  Street View error: {e}")
        return None


def post_tweet(text: str, image_path: Optional[str], creds: dict) -> Optional[str]:
    import tweepy

    auth = tweepy.OAuth1UserHandler(
        creds["TWITTER_API_KEY"], creds["TWITTER_API_SECRET"],
        creds["TWITTER_ACCESS_TOKEN"], creds["TWITTER_ACCESS_TOKEN_SECRET"],
    )
    api_v1 = tweepy.API(auth)
    client = tweepy.Client(
        consumer_key=creds["TWITTER_API_KEY"],
        consumer_secret=creds["TWITTER_API_SECRET"],
        access_token=creds["TWITTER_ACCESS_TOKEN"],
        access_token_secret=creds["TWITTER_ACCESS_TOKEN_SECRET"],
    )

    media_ids = None
    if image_path:
        print("  Uploading image...")
        media = api_v1.media_upload(filename=image_path)
        media_ids = [media.media_id]

    print("  Posting tweet...")
    resp = client.create_tweet(text=text, media_ids=media_ids)
    tweet_id = resp.data.get("id") if resp and resp.data else None
    return str(tweet_id) if tweet_id else None


def mark_posted(conn: sqlite3.Connection, lot_id: int, tweet_id: Optional[str]) -> None:
    conn.execute(
        "UPDATE lots SET posted = 1, tweet_id = ?, posted_at = ? WHERE id = ?",
        (tweet_id, datetime.now(timezone.utc).isoformat(), lot_id),
    )
    conn.commit()


def main():
    ap = argparse.ArgumentParser(description="@everylotSJ bot")
    ap.add_argument("--dry-run", action="store_true", help="Print tweet without posting")
    ap.add_argument("--id", dest="row_id", type=int, default=None, help="Force a specific row ID")
    args = ap.parse_args()

    creds = load_credentials()

    if not os.path.exists(DB_PATH):
        print(f"ERROR: {DB_PATH} not found. Run `python setup_db.py` first.")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    try:
        lot = get_lot(conn, row_id=args.row_id)
        if lot is None:
            msg = f"No lot found with ID {args.row_id}." if args.row_id else "No unposted lots remaining!"
            print(msg)
            sys.exit(0)

        print(f"Selected ID {lot['id']} — {lot['address']}")

        tweet_text = format_tweet(lot)
        print("---- tweet preview ----")
        print(tweet_text)
        print("-----------------------")
        print(f"  ({len(tweet_text)} chars)")

        image_path = None
        if lot["lat"] and lot["lon"] and creds.get("GOOGLE_API_KEY"):
            print("  Fetching Street View image...")
            image_path = fetch_street_view(lot["lat"], lot["lon"], creds["GOOGLE_API_KEY"])
            if image_path:
                print(f"  Saved image: {image_path}")
        elif not creds.get("GOOGLE_API_KEY"):
            print("  (no GOOGLE_API_KEY — skipping Street View)")

        try:
            if args.dry_run:
                print("[DRY RUN] Not posting.")
                if image_path:
                    print(f"[DRY RUN] Would attach image: {image_path}")
            else:
                missing = [k for k, v in creds.items() if k.startswith("TWITTER_") and not v]
                if missing:
                    print(f"ERROR: Missing Twitter credentials: {missing}")
                    sys.exit(1)
                tweet_id = post_tweet(tweet_text, image_path, creds)
                mark_posted(conn, lot["id"], tweet_id)
                print(f"Posted! Tweet ID: {tweet_id}")
        finally:
            if image_path and os.path.exists(image_path):
                os.unlink(image_path)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
