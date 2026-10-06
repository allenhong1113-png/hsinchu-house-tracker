import sqlite3
import hashlib
from datetime import datetime

DB_PATH = "houses.db"


def connect():
    con = sqlite3.connect(
        DB_PATH,
        check_same_thread=False
    )
    con.row_factory = sqlite3.Row
    return con


# ============================================================
# DATABASE INITIALIZATION + AUTO MIGRATION
# ============================================================

def init_db():

    con = connect()
    cur = con.cursor()

    # -------------------------
    # Houses
    # -------------------------

    cur.execute("""
    CREATE TABLE IF NOT EXISTS houses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fingerprint TEXT UNIQUE,
        name TEXT,
        district TEXT,
        address TEXT,
        price REAL,
        area REAL,
        age REAL,
        rooms INTEGER,
        parking TEXT,
        floor TEXT,
        source TEXT,
        url TEXT,
        lat REAL,
        lon REAL,
        work1_distance REAL,
        work2_distance REAL,
        first_seen TEXT,
        last_seen TEXT,
        active INTEGER DEFAULT 1,
        last_status TEXT DEFAULT 'existing'
    )
    """)

    # -------------------------
    # AUTO MIGRATION
    # -------------------------

    existing_columns = {
        row["name"]
        for row in cur.execute(
            "PRAGMA table_info(houses)"
        ).fetchall()
    }

    required_columns = {

        "work1_distance":
            "REAL",

        "work2_distance":
            "REAL",

        "last_status":
            "TEXT DEFAULT 'existing'",

        "active":
            "INTEGER DEFAULT 1",

        "lat":
            "REAL",

        "lon":
            "REAL"
    }

    for column, datatype in required_columns.items():

        if column not in existing_columns:

            cur.execute(
                f"""
                ALTER TABLE houses
                ADD COLUMN {column} {datatype}
                """
            )

    # -------------------------
    # Price History
    # -------------------------

    cur.execute("""
    CREATE TABLE IF NOT EXISTS price_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fingerprint TEXT,
        price REAL,
        seen_at TEXT
    )
    """)

    # -------------------------
    # Scan History
    # -------------------------

    cur.execute("""
    CREATE TABLE IF NOT EXISTS scan_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_time TEXT,
        raw_count INTEGER,
        unique_count INTEGER,
        qualified_count INTEGER
    )
    """)

    con.commit()
    con.close()


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def clean_text(value):

    if value is None:
        return ""

    return (
        str(value)
        .strip()
        .lower()
        .replace(" ", "")
    )


# ============================================================
# FINGERPRINT
# ============================================================

def make_fingerprint(h):

    name = clean_text(
        h.get("name")
    )

    district = clean_text(
        h.get("district")
    )

    address = clean_text(
        h.get("address")
    )

    floor = clean_text(
        h.get("floor")
    )

    try:

        area = round(
            float(
                h.get("area", 0)
            ),
            1
        )

    except:

        area = 0

    rooms = h.get(
        "rooms",
        ""
    )

    raw = (
        f"{name}|"
        f"{district}|"
        f"{address}|"
        f"{floor}|"
        f"{area}|"
        f"{rooms}"
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).
