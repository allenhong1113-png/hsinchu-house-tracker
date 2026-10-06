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
    ).hexdigest()


# ============================================================
# UPSERT HOUSE
# ============================================================

def upsert_house(h):

    con = connect()
    cur = con.cursor()

    fp = make_fingerprint(h)

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    row = cur.execute(
        """
        SELECT
            price,
            active
        FROM houses
        WHERE fingerprint=?
        """,
        (fp,)
    ).fetchone()

    # ========================================================
    # NEW HOUSE
    # ========================================================

    if row is None:

        status = "new"

        cur.execute("""
        INSERT INTO houses (
            fingerprint,
            name,
            district,
            address,
            price,
            area,
            age,
            rooms,
            parking,
            floor,
            source,
            url,
            lat,
            lon,
            work1_distance,
            work2_distance,
            first_seen,
            last_seen,
            active,
            last_status
        )

        VALUES (
            ?,?,?,?,?,?,?,?,?,?,
            ?,?,?,?,?,?,?,?,?,?
        )
        """, (

            fp,

            h.get("name"),
            h.get("district"),
            h.get("address"),

            h.get("price"),
            h.get("area"),
            h.get("age"),
            h.get("rooms"),

            h.get("parking"),
            h.get("floor"),

            h.get("source"),
            h.get("url"),

            h.get("lat"),
            h.get("lon"),

            h.get("work1_distance"),
            h.get("work2_distance"),

            now,
            now,

            1,
            status
        ))

    # ========================================================
    # EXISTING HOUSE
    # ========================================================

    else:

        old_price = row["price"]
        was_active = row["active"]

        new_price = h.get("price")

        if was_active == 0:

            status = "relisted"

        elif (
            new_price is not None
            and old_price is not None
            and new_price < old_price
        ):

            status = "price_drop"

        elif (
            new_price is not None
            and old_price is not None
            and new_price > old_price
        ):

            status = "price_up"

        else:

            status = "existing"

        cur.execute("""
        UPDATE houses

        SET
            name=?,
            district=?,
            address=?,
            price=?,
            area=?,
            age=?,
            rooms=?,
            parking=?,
            floor=?,
            source=?,
            url=?,
            lat=?,
            lon=?,
            work1_distance=?,
            work2_distance=?,
            last_seen=?,
            active=1,
            last_status=?

        WHERE fingerprint=?
        """, (

            h.get("name"),
            h.get("district"),
            h.get("address"),

            h.get("price"),
            h.get("area"),
            h.get("age"),
            h.get("rooms"),

            h.get("parking"),
            h.get("floor"),

            h.get("source"),
            h.get("url"),

            h.get("lat"),
            h.get("lon"),

            h.get("work1_distance"),
            h.get("work2_distance"),

            now,
            status,

            fp
        ))

    # ========================================================
    # PRICE HISTORY
    # ========================================================

    previous = cur.execute("""
        SELECT price
        FROM price_history

        WHERE fingerprint=?

        ORDER BY id DESC

        LIMIT 1
    """, (fp,)).fetchone()

    current_price = h.get(
        "price"
    )

    if (
        previous is None
        or previous["price"] != current_price
    ):

        cur.execute("""
        INSERT INTO price_history (
            fingerprint,
            price,
            seen_at
        )

        VALUES (?, ?, ?)
        """, (

            fp,
            current_price,
            now
        ))

    con.commit()
    con.close()

    return status, fp


# ============================================================
# MARK MISSING
# ============================================================

def mark_missing_inactive(
    seen_fingerprints
):

    con = connect()
    cur = con.cursor()

    rows = cur.execute("""
        SELECT fingerprint
        FROM houses
        WHERE active=1
    """).fetchall()

    seen = set(
        seen_fingerprints
    )

    for row in rows:

        fp = row[
            "fingerprint"
        ]

        if fp not in seen:

            cur.execute("""
            UPDATE houses

            SET
                active=0,
                last_status='delisted'

            WHERE fingerprint=?
            """, (fp,))

    con.commit()
    con.close()
