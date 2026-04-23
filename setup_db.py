"""Build lots.db from the San Jose Addresses MapServer (ArcGIS REST API).

Usage:
    python setup_db.py                 # full run (~395k addresses)
    python setup_db.py --limit 1000    # test with 1000 rows
    python setup_db.py --reset         # delete existing DB and start fresh
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import time

import requests

MAPSERVER_URL = (
    "https://geo.sanjoseca.gov/server/rest/services/OPN/OPN_OpenDataService/MapServer/36/query"
)
PAGE_SIZE = 2000
DB_PATH = "lots.db"
USER_AGENT = "everylotSJ-bot/1.0 (https://github.com/RamonGarciaGomez/everylotsj)"


def create_db(reset: bool = False) -> sqlite3.Connection:
    if reset:
        for f in [DB_PATH, DB_PATH + "-wal", DB_PATH + "-shm"]:
            if os.path.exists(f):
                os.remove(f)
                print(f"  Removed {f}")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lots (
            id INTEGER PRIMARY KEY,
            address TEXT,
            place_type TEXT,
            lat REAL,
            lon REAL,
            posted INTEGER DEFAULT 0,
            post_id TEXT,
            posted_at TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_posted_id ON lots(posted, id)")
    conn.commit()
    return conn


def get_total_count(session: requests.Session) -> int:
    try:
        r = session.get(MAPSERVER_URL, params={
            "where": "Status='Active'",
            "returnCountOnly": "true",
            "f": "json",
        }, timeout=30)
        return r.json().get("count", 0)
    except Exception:
        return 0


def fetch_page(session: requests.Session, offset: int) -> list[dict]:
    params = {
        "where": "Status='Active'",
        "outFields": "OBJECTID,Site_UID,FullMailing,Place_Type,Lat,Long",
        "returnGeometry": "false",
        "resultOffset": offset,
        "resultRecordCount": PAGE_SIZE,
        "f": "json",
    }
    for attempt in range(3):
        try:
            r = session.get(MAPSERVER_URL, params=params, timeout=30)
            r.raise_for_status()
            return r.json().get("features", [])
        except (requests.RequestException, ValueError) as e:
            if attempt == 2:
                raise
            print(f"  Retry {attempt + 1} after error: {e}")
            time.sleep(2)
    return []


def load_all(conn: sqlite3.Connection, limit: int | None) -> int:
    print("Loading addresses from San Jose MapServer...")

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    total_expected = get_total_count(session)
    if total_expected:
        print(f"  Expecting ~{total_expected:,} records from the server")

    inserted = 0
    offset = 0

    while True:
        if limit is not None and inserted >= limit:
            break

        features = fetch_page(session, offset)
        if not features:
            break

        for feat in features:
            attrs = feat.get("attributes", {})
            uid = attrs.get("Site_UID") or attrs.get("OBJECTID")
            address = (attrs.get("FullMailing") or "").strip()
            place_type = (attrs.get("Place_Type") or "").strip()
            lat = attrs.get("Lat")
            lon = attrs.get("Long")

            if not uid or not address or lat is None or lon is None:
                continue

            conn.execute(
                "INSERT OR IGNORE INTO lots (id, address, place_type, lat, lon) VALUES (?,?,?,?,?)",
                (uid, address, place_type, lat, lon),
            )
            inserted += 1

        conn.commit()
        offset += len(features)

        pct = f"{offset * 100 // total_expected}%" if total_expected else ""
        print(f"  Fetched {offset:,}/{total_expected:,} rows {pct} — {inserted:,} inserted...")

        if len(features) < PAGE_SIZE:
            break
        if limit is not None and inserted >= limit:
            break

    print(f"Done. {inserted:,} addresses in {DB_PATH}")
    return inserted


def main():
    ap = argparse.ArgumentParser(description="Build lots.db for @everylotSJ")
    ap.add_argument("--limit", type=int, default=None, help="Limit to N rows (for testing)")
    ap.add_argument("--reset", action="store_true", help="Delete existing DB and start fresh")
    args = ap.parse_args()

    conn = create_db(reset=args.reset)
    try:
        load_all(conn, args.limit)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
