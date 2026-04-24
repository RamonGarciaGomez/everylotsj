"""@everylotSJ Mastodon bot — posts one San Jose address every 2 minutes.

Usage:
    python bot.py                  # pick the next unposted address and post it
    python bot.py --dry-run        # print the post without publishing
    python bot.py --id 12345       # force a specific row ID
    python bot.py --backfill       # backfill Street View images for posted lots
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Optional

import requests
from dotenv import load_dotenv
from mastodon import Mastodon, MastodonRatelimitError

DB_PATH = "lots.db"
CURRENT_ZIP_PATH = ".current_zip"
PENDING_POST_PATH = ".pending_post"
METRICS_PATH = "metrics.json"
STREET_VIEW_URL = "https://maps.googleapis.com/maps/api/streetview"
STREET_VIEW_METADATA_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"
MAPILLARY_API_URL = "https://graph.mapillary.com/images"
GOOGLE_PLACES_URL = "https://places.googleapis.com/v1/places:searchNearby"
USER_AGENT = "everylotSJ-bot/1.0 (https://github.com/RamonGarciaGomez/everylotsj)"

MILESTONE_INTERVALS = [1000, 5000, 10000, 50000, 100000]

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
    "95101": "Downtown",
    "95103": "Downtown",
    "95109": "Downtown",
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
    "95137": "South San Jose",
    "95138": "Silver Creek",
    "95139": "South San Jose",
    "95140": "Mount Hamilton",
    "95141": "Silver Creek",
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
        "MAPILLARY_ACCESS_TOKEN": os.getenv("MAPILLARY_ACCESS_TOKEN"),
        "HEALTHCHECK_URL": os.getenv("HEALTHCHECK_URL"),
    }


def get_lot(conn: sqlite3.Connection, row_id: Optional[int] = None) -> Optional[sqlite3.Row]:
    cur = conn.cursor()
    if row_id is not None:
        cur.execute("SELECT * FROM lots WHERE id = ?", (row_id,))
    else:
        cur.execute("SELECT * FROM lots WHERE posted = 0 ORDER BY id ASC LIMIT 1")
    return cur.fetchone()


def extract_zip(address: str) -> Optional[str]:
    m = re.search(r"\bCA\s+(9\d{4})\b", address)
    return m.group(1) if m else None


def get_posted_count(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT COUNT(*) FROM lots WHERE posted = 1").fetchone()
        return row[0] if row else 0
    except Exception as e:
        print(f"  WARNING: get_posted_count failed: {e}")
        return 0


def get_total_count(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT COUNT(*) FROM lots").fetchone()
        return row[0] if row else 0
    except Exception as e:
        print(f"  WARNING: get_total_count failed: {e}")
        return 0


def make_google_maps_link(lat: float, lon: float) -> str:
    return f"https://maps.google.com/?q={lat},{lon}"


def format_post(lot: sqlite3.Row, posted_count: int = 0, place_name: Optional[str] = None) -> str:
    lines = []

    # Milestone check
    for m in MILESTONE_INTERVALS:
        if posted_count > 0 and posted_count % m == 0:
            lines.append(f"🎉 Milestone: {posted_count:,} addresses posted!")
            break

    lines.append(f"📍 {lot['address']}")

    place = PLACE_TYPES.get(lot["place_type"] or "")
    if place:
        emoji, label = place
        lines.append(f"{emoji} Property type: {label}")

    if place_name:
        lines.append(f"🏪 {place_name}")

    if lot["lat"] is not None and lot["lon"] is not None:
        lines.append(f"🗺️ {make_google_maps_link(lot['lat'], lot['lon'])}")

    lines.append("#SanJose #everylotSJ")
    return "\n".join(lines)


def format_bio(lot: sqlite3.Row) -> str:
    # Prefer stored zip/neighborhood from DB row, fall back to extraction
    try:
        zipcode = lot["zip"] or extract_zip(lot["address"])
        neighborhood = lot["neighborhood"] or (ZIP_NEIGHBORHOODS.get(zipcode, "San Jose") if zipcode else "San Jose")
    except (IndexError, KeyError):
        zipcode = extract_zip(lot["address"])
        neighborhood = ZIP_NEIGHBORHOODS.get(zipcode, "San Jose") if zipcode else "San Jose"
    location = f"{neighborhood} ({zipcode})" if zipcode else neighborhood
    return (
        f"posting every address in san josé one by one (all 394k)\n"
        f"📍 currently in: {location.lower()}\n"
        f"created by ramón → ramongarciagomez.com"
    )


def street_view_has_image(lat: float, lon: float, api_key: str) -> bool:
    try:
        r = requests.get(
            STREET_VIEW_METADATA_URL,
            params={"location": f"{lat},{lon}", "key": api_key},
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
        data = r.json()
        status = data.get("status", "")
        # Feature 12 — quota back-off
        if status in ("OVER_QUERY_LIMIT", "OVER_DAILY_LIMIT"):
            print(f"  WARNING: Google Street View quota exceeded ({status}). Skipping Street View this run.")
            return False
        return r.status_code == 200 and status == "OK"
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
        if r.status_code != 200:
            print(f"  Street View fetch failed (status {r.status_code}).")
            return None
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp.write(r.content)
        tmp.close()
        return tmp.name
    except requests.RequestException as e:
        print(f"  Street View error: {e}")
        return None


def fetch_mapillary_image(lat: float, lon: float, token: str) -> Optional[str]:
    try:
        bbox = f"{lon-0.001},{lat-0.001},{lon+0.001},{lat+0.001}"
        r = requests.get(
            MAPILLARY_API_URL,
            params={
                "access_token": token,
                "bbox": bbox,
                "fields": "id,thumb_1024_url",
                "limit": 1,
            },
            timeout=20,
        )
        data = r.json()
        entries = data.get("data", [])
        if not entries:
            return None
        url = entries[0].get("thumb_1024_url")
        if not url:
            return None
        img_r = requests.get(url, timeout=30)
        if img_r.status_code != 200:
            return None
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp.write(img_r.content)
        tmp.close()
        return tmp.name
    except Exception as e:
        print(f"  Mapillary error: {e}")
        return None


def get_place_name(lat: float, lon: float, api_key: str) -> Optional[str]:
    try:
        r = requests.post(
            GOOGLE_PLACES_URL,
            headers={
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": "places.displayName",
                "Content-Type": "application/json",
            },
            json={
                "includedTypes": ["establishment"],
                "maxResultCount": 1,
                "locationRestriction": {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lon},
                        "radius": 30.0,
                    }
                },
            },
            timeout=15,
        )
        data = r.json()
        return data["places"][0]["displayName"]["text"]
    except Exception:
        return None


def post_to_mastodon(
    text: str,
    image_path: Optional[str],
    address: str,
    creds: dict,
    neighborhood: str = "",
    place_type_label: str = "",
) -> tuple[Optional[str], Mastodon]:
    mastodon = Mastodon(
        client_id=creds["MASTODON_CLIENT_KEY"],
        client_secret=creds["MASTODON_CLIENT_SECRET"],
        access_token=creds["MASTODON_ACCESS_TOKEN"],
        api_base_url=creds["MASTODON_INSTANCE_URL"],
    )

    media_ids = None
    if image_path:
        print("  Uploading image...")
        if place_type_label:
            alt_text = f"Street View of {address} — {place_type_label} in {neighborhood}"
        else:
            alt_text = f"Street View of {address} in {neighborhood}"
        media = mastodon.media_post(image_path, mime_type="image/jpeg", description=alt_text)
        media_ids = [media["id"]]

    print("  Posting to Mastodon...")
    # Bug 10 + Feature 17 — retry loop with rate-limit awareness
    last_exc = None
    for attempt in range(3):
        try:
            status = mastodon.status_post(text, media_ids=media_ids, visibility="public")
            return str(status["id"]) if status else None, mastodon
        except MastodonRatelimitError as e:
            last_exc = e
            print(f"  Rate limited (attempt {attempt + 1}/3), sleeping 60s...")
            time.sleep(60)
        except Exception as e:
            last_exc = e
            if attempt < 2:
                print(f"  Post failed (attempt {attempt + 1}/3): {e}, retrying in 5s...")
                time.sleep(5)
    raise last_exc


def update_bio_if_changed(mastodon: Mastodon, lot: sqlite3.Row) -> None:
    # Prefer stored zip from DB row, fall back to extraction
    try:
        zipcode = lot["zip"] or extract_zip(lot["address"])
    except (IndexError, KeyError):
        zipcode = extract_zip(lot["address"])
    if not zipcode:
        return
    last_zip = None
    if os.path.exists(CURRENT_ZIP_PATH):
        with open(CURRENT_ZIP_PATH) as f:
            last_zip = f.read().strip()
    if zipcode == last_zip:
        return
    bio = format_bio(lot)
    print(f"  Zip changed {last_zip} → {zipcode}, updating bio...")
    mastodon.account_update_credentials(note=bio)
    with open(CURRENT_ZIP_PATH, "w") as f:
        f.write(zipcode)


def mark_posted(
    conn: sqlite3.Connection,
    lot_id: int,
    post_id: Optional[str],
    image_source: Optional[str] = None,
) -> None:
    conn.execute(
        "UPDATE lots SET posted = 1, post_id = ?, posted_at = ?, image_source = ? WHERE id = ?",
        (post_id, datetime.now(timezone.utc).isoformat(), image_source, lot_id),
    )
    conn.commit()


def check_and_recover_pending(conn: sqlite3.Connection) -> None:
    if not os.path.exists(PENDING_POST_PATH):
        return
    try:
        with open(PENDING_POST_PATH) as f:
            data = json.load(f)
        lot_id = data.get("id")
        if lot_id is None:
            os.unlink(PENDING_POST_PATH)
            return
        row = conn.execute("SELECT posted FROM lots WHERE id = ?", (lot_id,)).fetchone()
        if row and row[0] == 0:
            print(f"  WARNING: Recovering pending post for lot_id={lot_id} — marking as posted (post_id=None).")
            mark_posted(conn, lot_id, post_id=None)
        os.unlink(PENDING_POST_PATH)
    except Exception as e:
        print(f"  WARNING: Could not process pending post file: {e}")


def ping_healthcheck(url: str) -> None:
    try:
        requests.get(url, timeout=10)
    except Exception:
        pass


def update_metrics(lot: sqlite3.Row, image_source: Optional[str], posted_count: int) -> None:
    try:
        total = 0
        try:
            conn_m = sqlite3.connect(DB_PATH)
            total = conn_m.execute("SELECT COUNT(*) FROM lots").fetchone()[0]
            conn_m.close()
        except Exception:
            pass
        pct = round(posted_count * 100 / total, 4) if total else 0.0
        now_iso = datetime.now(timezone.utc).isoformat()

        try:
            zip_val = lot["zip"]
        except (IndexError, KeyError):
            zip_val = None
        try:
            neighborhood_val = lot["neighborhood"]
        except (IndexError, KeyError):
            neighborhood_val = None

        metrics = {
            "last_post": {
                "id": lot["id"],
                "address": lot["address"],
                "zip": zip_val,
                "neighborhood": neighborhood_val,
                "place_type": lot["place_type"],
                "image_source": image_source,
                "posted_at": now_iso,
            },
            "total_posted": posted_count,
            "total_lots": total,
            "percent_complete": pct,
            "updated_at": now_iso,
        }
        tmp_path = METRICS_PATH + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(metrics, f, indent=2)
        os.replace(tmp_path, METRICS_PATH)
    except Exception as e:
        print(f"  WARNING: metrics update failed: {e}")


def main():
    ap = argparse.ArgumentParser(description="@everylotSJ bot")
    ap.add_argument("--dry-run", action="store_true", help="Print post without publishing")
    ap.add_argument("--id", dest="row_id", type=int, default=None, help="Force a specific row ID")
    ap.add_argument("--backfill", action="store_true", help="Backfill Street View images for posted lots")
    args = ap.parse_args()

    creds = load_credentials()

    if not os.path.exists(DB_PATH):
        print(f"ERROR: {DB_PATH} not found. Run `python setup_db.py` first.")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Bug 1 — recover from interrupted post
    check_and_recover_pending(conn)

    # Feature 14 — backfill mode
    if args.backfill:
        rows = conn.execute(
            "SELECT * FROM lots WHERE posted = 1 AND image_source IS NULL "
            "AND post_id IS NOT NULL AND lat IS NOT NULL AND lon IS NOT NULL LIMIT 10"
        ).fetchall()
        if not rows:
            print("No lots to backfill.")
            conn.close()
            return

        mastodon = Mastodon(
            client_id=creds["MASTODON_CLIENT_KEY"],
            client_secret=creds["MASTODON_CLIENT_SECRET"],
            access_token=creds["MASTODON_ACCESS_TOKEN"],
            api_base_url=creds["MASTODON_INSTANCE_URL"],
        )

        for i, lot in enumerate(rows, 1):
            print(f"[{i}/{len(rows)}] Backfilling lot {lot['id']} — {lot['address']}")
            image_path = None
            if creds.get("GOOGLE_API_KEY"):
                image_path = fetch_street_view(lot["lat"], lot["lon"], creds["GOOGLE_API_KEY"])
            if image_path is None and creds.get("MAPILLARY_ACCESS_TOKEN"):
                image_path = fetch_mapillary_image(lot["lat"], lot["lon"], creds["MAPILLARY_ACCESS_TOKEN"])
            if image_path:
                try:
                    alt_text = f"Street View of {lot['address']}"
                    media = mastodon.media_post(image_path, mime_type="image/jpeg", description=alt_text)
                    mastodon.status_post(
                        "📸 Adding Street View image to this address.",
                        in_reply_to_id=lot["post_id"],
                        media_ids=[media["id"]],
                        visibility="public",
                    )
                    conn.execute("UPDATE lots SET image_source = 'backfill' WHERE id = ?", (lot["id"],))
                    conn.commit()
                    print(f"  Backfilled lot {lot['id']}.")
                except Exception as e:
                    print(f"  Error backfilling lot {lot['id']}: {e}")
                finally:
                    if os.path.exists(image_path):
                        os.unlink(image_path)
            else:
                print(f"  No image found for lot {lot['id']}, skipping.")
        conn.close()
        return

    try:
        conn.execute("BEGIN IMMEDIATE")
        lot = get_lot(conn, row_id=args.row_id)
        if lot is None:
            conn.rollback()
            msg = f"No lot found with ID {args.row_id}." if args.row_id else "No unposted lots remaining!"
            print(msg)
            sys.exit(0)

        print(f"Selected ID {lot['id']} — {lot['address']}")

        posted_count = get_posted_count(conn)

        # Feature 5 — place name for BU lots
        place_name = None
        if lot["place_type"] == "BU" and lot["lat"] is not None and lot["lon"] is not None and creds.get("GOOGLE_API_KEY"):
            place_name = get_place_name(lot["lat"], lot["lon"], creds["GOOGLE_API_KEY"])

        post_text = format_post(lot, posted_count=posted_count, place_name=place_name)
        bio_text = format_bio(lot)
        print("---- post preview ----")
        print(post_text)
        print("---- bio preview ----")
        print(bio_text)
        print("----------------------")

        image_path = None
        image_source = None

        if lot["lat"] is not None and lot["lon"] is not None and creds.get("GOOGLE_API_KEY"):
            print("  Fetching Street View image...")
            image_path = fetch_street_view(lot["lat"], lot["lon"], creds["GOOGLE_API_KEY"])
            if image_path:
                image_source = "streetview"
                print(f"  Saved image: {image_path}")
        elif not creds.get("GOOGLE_API_KEY"):
            print("  (no GOOGLE_API_KEY — skipping Street View)")

        # Feature 4 — Mapillary fallback
        if image_path is None and creds.get("MAPILLARY_ACCESS_TOKEN") and lot["lat"] is not None and lot["lon"] is not None:
            print("  Trying Mapillary fallback...")
            image_path = fetch_mapillary_image(lot["lat"], lot["lon"], creds["MAPILLARY_ACCESS_TOKEN"])
            if image_path:
                image_source = "mapillary"
                print(f"  Saved Mapillary image: {image_path}")

        # Resolve neighborhood for alt text
        try:
            neighborhood = lot["neighborhood"] or (ZIP_NEIGHBORHOODS.get(extract_zip(lot["address"]) or "", "San Jose"))
        except (IndexError, KeyError):
            zipcode = extract_zip(lot["address"])
            neighborhood = ZIP_NEIGHBORHOODS.get(zipcode, "San Jose") if zipcode else "San Jose"

        place_type_info = PLACE_TYPES.get(lot["place_type"] or "")
        place_type_label = place_type_info[1] if place_type_info else ""

        mastodon_client = None
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
                    # Bug 1 — write pending post marker before posting
                    with open(PENDING_POST_PATH, "w") as f:
                        json.dump({"id": lot["id"]}, f)

                    post_id, mastodon_client = post_to_mastodon(
                        post_text,
                        image_path,
                        lot["address"],
                        creds,
                        neighborhood=neighborhood,
                        place_type_label=place_type_label,
                    )
                    mark_posted(conn, lot["id"], post_id, image_source=image_source)
                    print(f"Posted! Status ID: {post_id}")

                    # Bug 1 — delete pending post marker after success
                    if os.path.exists(PENDING_POST_PATH):
                        os.unlink(PENDING_POST_PATH)

                    # Feature 13 — health check ping
                    if creds.get("HEALTHCHECK_URL"):
                        ping_healthcheck(creds["HEALTHCHECK_URL"])

                    # Feature 19 — update metrics
                    update_metrics(lot, image_source, posted_count + 1)

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

    # Bug 2 — bio update AFTER try/except, bio failure does not crash bot
    if mastodon_client is not None and not args.dry_run:
        try:
            update_bio_if_changed(mastodon_client, lot)
        except Exception as e:
            print(f"  WARNING: Bio update failed (post already succeeded): {e}")


if __name__ == "__main__":
    main()
