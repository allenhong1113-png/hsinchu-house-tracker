import os
import pandas as pd

from database import (
    init_db,
    upsert_house,
    mark_missing_inactive
)

CSV_PATH = "data/houses.csv"

init_db()

if not os.path.exists(CSV_PATH):
    print("找不到 data/houses.csv")
    raise SystemExit

df = pd.read_csv(CSV_PATH)

required = [
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
    "url"
]

missing = [x for x in required if x not in df.columns]

if missing:
    print("缺少欄位:", missing)
    raise SystemExit

# ---------------------------
# 去除完全重複列
# ---------------------------

raw_count = len(df)
df = df.drop_duplicates()

print("原始筆數:", raw_count)
print("完全去重後:", len(df))

seen = []

stats = {
    "new": 0,
    "price_drop": 0,
    "price_up": 0,
    "relisted": 0,
    "existing": 0
}

for _, r in df.iterrows():

    def value(name, default=None):
        v = r.get(name, default)
        if pd.isna(v):
            return default
        return v

    house = {
        "name": value("name", ""),
        "district": value("district", ""),
        "address": value("address", ""),
        "price": float(value("price", 0)),
        "area": float(value("area", 0)),
        "age": float(value("age", 0)),
        "rooms": int(value("rooms", 0)),
        "parking": value("parking", ""),
        "floor": value("floor", ""),
        "source": value("source", ""),
        "url": value("url", ""),
        "lat": value("lat"),
        "lon": value("lon"),
        "work1_distance": value("work1_distance"),
        "work2_distance": value("work2_distance")
    }

    status, fp = upsert_house(house)

    seen.append(fp)

    if status in stats:
        stats[status] += 1

# 等真正做到「完整市場掃描」再打開這一行
# mark_missing_inactive(seen)

print()
print("===== 本次結果 =====")
print("新增:", stats["new"])
print("降價:", stats["price_drop"])
print("漲價:", stats["price_up"])
print("重新上架:", stats["relisted"])
print("既有:", stats["existing"])
