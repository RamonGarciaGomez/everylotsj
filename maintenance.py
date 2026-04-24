"""Database maintenance: integrity check and VACUUM.

Usage: python maintenance.py
"""
from __future__ import annotations
import sqlite3
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

DB_PATH = "lots.db"

def main():
    load_dotenv()
    if not os.path.exists(DB_PATH):
        print(f"ERROR: {DB_PATH} not found.")
        return
    conn = sqlite3.connect(DB_PATH)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        print(f"Integrity check: {result}")
        freelist = conn.execute("PRAGMA freelist_count").fetchone()[0]
        print(f"Freelist pages: {freelist}")
        total = conn.execute("SELECT COUNT(*) FROM lots").fetchone()[0]
        posted = conn.execute("SELECT COUNT(*) FROM lots WHERE posted = 1").fetchone()[0]
        unposted = total - posted
        print(f"Lots: {total:,} total, {posted:,} posted, {unposted:,} remaining")
        pct = posted * 100 / total if total else 0
        print(f"Progress: {pct:.2f}%")
        print("Running VACUUM...")
        conn.execute("VACUUM")
        print(f"VACUUM complete. ({datetime.now(timezone.utc).isoformat()})")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
