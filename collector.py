"""Collect public listings atomically. Failure never silently imports old CSV."""
import json
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from Sources.source_yungching import collect

DATA_DIR = Path(__file__).resolve().parent / "data"
OUTPUT = DATA_DIR / "houses.csv"
STANDARD_COLUMNS = ["listing_id", "name", "title", "district", "address", "price", "area", "age", "rooms", "parking", "floor", "source", "url", "lat", "lon", "work1_distance", "work2_distance", "collected_at", "layout_status", "source_page", "geocode_status", "route_status", "geocode_provider", "route_provider"]


def normalize(df):
    df = df.copy()
    for col in STANDARD_COLUMNS:
        if col not in df:
            df[col] = None
    return df[STANDARD_COLUMNS].drop_duplicates(["source", "listing_id"])


def collect_all():
    DATA_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    datasets, reports = collect(timestamp)
    report = dict(collected_at=timestamp, sources=reports, complete_market_scan=False,
                  scope="PoC: first public search page in each of five regions", raw_count=sum(len(d) for d in datasets))
    if not datasets or any(r["status"] != "success" for r in reports):
        report.update(status="failed", published=False)
        (DATA_DIR / "collection_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        raise RuntimeError("Incomplete/failed collection; prior CSV retained; import must not run")
    df = normalize(pd.concat(datasets, ignore_index=True))
    report.update(status="success", published=True, unique_count=len(df))
    tmp = OUTPUT.with_suffix(".tmp")
    df.to_csv(tmp, index=False, encoding="utf-8-sig")
    tmp.replace(OUTPUT)
    (DATA_DIR / "collection_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return df


if __name__ == "__main__":
    collect_all()
