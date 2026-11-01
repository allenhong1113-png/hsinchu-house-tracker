"""Collect public listings atomically. Failure never silently imports old CSV."""
import json
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from Sources.source_yungching import collect, PublicClient
from listing_validation import verify_listings

DATA_DIR = Path(__file__).resolve().parent / "data"
OUTPUT = DATA_DIR / "houses.csv"
STANDARD_COLUMNS = ["listing_id", "name", "title", "district", "address", "price", "area", "age", "rooms", "parking", "floor", "source", "url", "lat", "lon", "work1_distance", "work2_distance", "collected_at", "layout_status", "source_page", "geocode_status", "route_status", "geocode_provider", "route_provider"]


def normalize(df):
    df = df.copy()
    for col in STANDARD_COLUMNS:
        if col not in df:
            df[col] = None
    return df[STANDARD_COLUMNS].drop_duplicates(["source", "listing_id"])



def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def merge_snapshot(previous, datasets):
    # Search absence never proves delisting, even after a complete filtered query.
    # Current rows win; retained rows keep their original last-seen timestamp.
    frames = [d for d in datasets if not d.empty]
    if not previous.empty:
        frames.append(previous)
    return normalize(pd.concat(frames, ignore_index=True)) if frames else pd.DataFrame(columns=STANDARD_COLUMNS)


def collect_all(collectors=None, client=None):
    DATA_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    client = client or PublicClient()
    previous = pd.read_csv(OUTPUT, dtype={'listing_id': str}) if OUTPUT.exists() else pd.DataFrame()
    datasets, reports = [], []
    # Isolate adapters too: a failed adapter cannot discard another's successful rows.
    for adapter in (collectors if collectors is not None else [collect]):
        try:
            frames, source_reports = adapter(timestamp, client=client)
            datasets.extend(frames)
            reports.extend(source_reports)
        except Exception as exc:
            reports.append(dict(source=adapter.__name__, status='failed', error=str(exc), count=0))
    df = merge_snapshot(previous, datasets)
    checks = verify_listings(df, timestamp, client=client)
    write_json(DATA_DIR / 'listing_checks.json', checks)
    raw_count = sum(len(d) for d in datasets)
    usable = raw_count > 0 or any(r.get('status') == 'success' for r in reports)
    complete = bool(reports) and all(r.get('complete', False) for r in reports)
    report = dict(collected_at=timestamp, sources=reports, complete_market_scan=False,
                  complete_configured_queries=complete, scope='All accessible public pagination in five regions',
                  raw_count=raw_count, unique_count=len(df),
                  newly_observed_unique_count=len(normalize(pd.concat(datasets, ignore_index=True))) if raw_count else 0,
                  retained_count=len(df) - (len(normalize(pd.concat(datasets, ignore_index=True))) if raw_count else 0),
                  verified_available=checks['verified_available'], published=usable and not df.empty,
                  status=('success' if complete else 'partial') if usable else 'failed',
                  retained_snapshot=not previous.empty)
    write_json(DATA_DIR / 'last_collection_attempt.json', report)
    if not usable or df.empty:
        raise RuntimeError('No publishable new collection; prior snapshot and history retained; detail checks recorded')
    temporary = OUTPUT.with_suffix('.tmp')
    df.to_csv(temporary, index=False, encoding='utf-8-sig')
    temporary.replace(OUTPUT)
    write_json(DATA_DIR / 'collection_report.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return df


if __name__ == '__main__':
    collect_all()
