import sqlite3
import hashlib
from datetime import datetime

DB_PATH = "houses.db"

def connect():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

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
        work1_distance REAL,
        work2_distance REAL,
        first_seen TEXT,
        last_seen TEXT,
        active INTEGER DEFAULT 1,
        last_status TEXT DEFAULT 'existing'
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

def clean_text(v):
    return str(v or "").strip().lower().replace(" ", "")

def make_fingerprint(h):
    # 不使用價格：降價後仍應辨識成同一戶
    name = clean_text(h.get("name"))
    district = clean_text(h.get("district"))
    address = clean_text(h.get("address"))
    floor = clean_text(h.get("floor"))

    try:
        area = round(float(h.get("area", 0)), 1)
    except:
        area = 0

    rooms = h.get("rooms", "")

    raw = f"{name}|{district}|{address}|{floor}|{area}|{rooms}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def upsert_house(h):
    con = connect()
    cur = con.cursor()

    fp = make_fingerprint(h)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    row = cur.execute(
        "SELECT price, active FROM houses WHERE fingerprint=?",
        (fp,)
    ).fetchone()

    if row is None:
        status = "new"

        cur.execute("""
        INSERT INTO houses (
            fingerprint,name,district,address,
            price,area,age,rooms,parking,floor,
            source,url,lat,lon,
            work1_distance,work2_distance,
            first_seen,last_seen,active,last_status
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)
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
            status
        ))

    else:
        old_price = row["price"]
        was_active = row["active"]

        if was_active == 0:
            status = "relisted"
        elif h.get("price") is not None and old_price is not None and h["price"] < old_price:
            status = "price_drop"
        elif h.get("price") is not None and old_price is not None and h["price"] > old_price:
            status = "price_up"
        else:
            status = "existing"

        cur.execute("""
        UPDATE houses SET
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

    # 只有價格改
