import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

OUTPUT = DATA_DIR / "houses.csv"


STANDARD_COLUMNS = [
    "listing_id",
    "name",
    "district",
    "address",
    "price",
    "area",
    "age",
    "rooms",
    "parking",
    "floor",
    "source",
    "url",
    "lat",
    "lon",
    "work1_distance",
    "work2_distance",
    "collected_at"
]


def normalize(df):

    for col in STANDARD_COLUMNS:
        if col not in df.columns:
            df[col] = None

    return df[STANDARD_COLUMNS]


def collect_all():

    datasets = []

    # ----------------------------------
    # 之後每個來源放在這裡
    # ----------------------------------

    try:
        from sources.source_591 import collect
        datasets.append(collect())
    except Exception as e:
        print("591:", e)

    try:
        from sources.source_yungching import collect
        datasets.append(collect())
    except Exception as e:
        print("永慶:", e)

    try:
        from sources.source_rakuya import collect
        datasets.append(collect())
    except Exception as e:
        print("樂屋:", e)

    if not datasets:
        print("沒有成功取得資料")
        return

    df = pd.concat(
        datasets,
        ignore_index=True
    )

    df = normalize(df)

    # URL 完全相同
    df = df.drop_duplicates(
        subset=["source", "listing_id"]
    )

    # 第二層：疑似同一戶
    df["dedup_key"] = (
        df["name"].fillna("").astype(str)
        + "|"
        + df["district"].fillna("").astype(str)
        + "|"
        + df["area"].fillna(0).round(1).astype(str)
        + "|"
        + df["floor"].fillna("").astype(str)
        + "|"
        + df["rooms"].fillna(0).astype(str)
    )

    df = df.drop_duplicates(
        subset=["dedup_key"]
    )

    df = df.drop(
        columns=["dedup_key"]
    )

    df.to_csv(
        OUTPUT,
        index=False,
        encoding="utf-8-sig"
    )

    print("======================")
    print("取得:", len(df))
    print("輸出:", OUTPUT)
    print("======================")


if __name__ == "__main__":
    collect_all()
