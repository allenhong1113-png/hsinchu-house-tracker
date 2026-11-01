"""Shared idempotent importer used by Actions and Streamlit bootstrap."""
import hashlib
import json
from pathlib import Path
import pandas as pd
from database import connect, init_db, upsert_house

CSV_PATH = Path(__file__).resolve().parent / "data/houses.csv"


def import_csv(path=CSV_PATH):
    init_db()
    content = Path(path).read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    con = connect()
    con.execute("CREATE TABLE IF NOT EXISTS imports (digest TEXT PRIMARY KEY, imported_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    if con.execute("SELECT 1 FROM imports WHERE digest=?", (digest,)).fetchone():
        con.close()
        return {"already_imported": True}
    con.commit()
    con.close()
    df = pd.read_csv(path, dtype={"listing_id": str})
    required = {"listing_id", "source", "url", "collected_at", "price", "rooms"}
    if not required.issubset(df.columns) or df.empty:
        raise ValueError("CSV lacks real listing provenance or contains no listings")
    # Validate the entire batch before any writes. Unknown age/parking remain unknown.
    if df[list(required)].isna().any().any():
        raise ValueError("Missing required listing provenance/numeric fields")
    if not df.url.str.startswith("https://buy.yungching.com.tw/house/").all():
        raise ValueError("Unsupported listing URL")
    stats = {}
    for record in df.to_dict("records"):
        house = {k: (None if pd.isna(v) else v) for k, v in record.items()}
        # Incoming CSV cannot assert guessed coordinates or unverified distances.
        if house.get("geocode_status") != "verified_address":
            house.update(lat=None, lon=None)
        if house.get("route_status") != "verified_road":
            house.update(work1_distance=None, work2_distance=None)
        # Carry-forward rows must not reset last_seen, status or price history.
        from database import make_fingerprint
        with connect() as existing_con:
            old = existing_con.execute('SELECT collected_at FROM houses WHERE fingerprint=?',
                                       (make_fingerprint(house),)).fetchone()
        if old and old['collected_at'] == house.get('collected_at'):
            stats['retained'] = stats.get('retained', 0) + 1
            continue
        status, _ = upsert_house(house)
        stats[status] = stats.get(status, 0) + 1
    con = connect()
    con.execute("INSERT INTO imports(digest) VALUES (?)", (digest,))
    con.commit()
    con.close()
    print(json.dumps({"imported": len(df), "statuses": stats}, ensure_ascii=False))
    return stats


if __name__ == "__main__":
    import_csv()
