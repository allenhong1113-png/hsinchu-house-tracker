import sqlite3
from datetime import datetime

DB_PATH = "houses.db"

def connect():
    return sqlite3.connect(DB_PATH)

def init_db():
    con = connect()
    cur = con.cursor()

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
        first_seen TEXT,
        last_seen TEXT,
        active INTEGER DEFAULT 1
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS price_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fingerprint TEXT,
        price REAL,
        seen_at TEXT
    )
    """)

    con.commit()
    con.close()

def make_fingerprint(h):
    # 初版：社區 + 區域 + 坪數 + 樓層 + 房數
    area = round(float(h.get("area", 0)), 1)

    return "|".join([
        str(h.get("name", "")).strip(),
        str(h.get("district", "")).strip(),
        str(area),
        str(h.get("floor", "")).strip(),
        str(h.get("rooms", "")).strip()
    ])

def upsert_house(h):
    con = connect()
    cur = con.cursor()

    fp = make_fingerprint(h)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute(
        "SELECT price FROM houses WHERE fingerprint=?",
        (fp,)
    )

    old = cur.fetchone()

    status = "existing"

    if old is None:
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
            first_seen,
            last_seen,
            active
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
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
            now,
            now
        ))

    else:
        old_price = old[0]

        if h.get("price") < old_price:
            status = "price_drop"

        elif h.get("price") > old_price:
            status = "price_up"

        cur.execute("""
        UPDATE houses
        SET
            price=?,
            age=?,
            parking=?,
            source=?,
            url=?,
            lat=?,
            lon=?,
            last_seen=?,
            active=1
        WHERE fingerprint=?
        """, (
            h.get("price"),
            h.get("age"),
            h.get("parking"),
            h.get("source"),
            h.get("url"),
            h.get("lat"),
            h.get("lon"),
            now,
            fp
        ))

    cur.execute("""
    INSERT INTO price_history (
        fingerprint,
        price,
        seen_at
    )
    VALUES (?, ?, ?)
    """, (
        fp,
        h.get("price"),
        now
    ))

    con.commit()
    con.close()

    return status

def load_houses():
    con = connect()

    rows = con.execute("""
    SELECT *
    FROM houses
    WHERE active=1
    ORDER BY price ASC
    """).fetchall()

    columns = [
        "id", "fingerprint", "name", "district",
        "address", "price", "area", "age",
        "rooms", "parking", "floor", "source",
        "url", "lat", "lon", "first_seen",
        "last_seen", "active"
    ]

    con.close()

    return rows, columns
