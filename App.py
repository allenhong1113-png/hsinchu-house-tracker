import os
import sqlite3
import pandas as pd
import streamlit as st

from database import init_db, upsert_house

# ============================================================
# CONFIG
# ============================================================

st.set_page_config(
    page_title="新竹雙通勤找房",
    page_icon="🏠",
    layout="wide"
)

DB_PATH = "houses.db"
CSV_PATH = "data/houses.csv"

init_db()

# ============================================================
# AUTO IMPORT CSV
# ============================================================

def import_csv():

    if not os.path.exists(CSV_PATH):
        return

    df_csv = pd.read_csv(CSV_PATH)

    for _, r in df_csv.iterrows():

        def val(key, default=None):
            if key not in r:
                return default

            v = r[key]

            if pd.isna(v):
                return default

            return v

        h = {
            "name": val("name", ""),
            "district": val("district", ""),
            "address": val("address", ""),
            "price": float(val("price", 0)),
            "area": float(val("area", 0)),
            "age": float(val("age", 0)),
            "rooms": int(val("rooms", 0)),
            "parking": val("parking", ""),
            "floor": val("floor", ""),
            "source": val("source", ""),
            "url": val("url", ""),
            "lat": val("lat"),
            "lon": val("lon"),
            "work1_distance": val("work1_distance"),
            "work2_distance": val("work2_distance")
        }

        upsert_house(h)

import_csv()

# ============================================================
# DATABASE LOADERS
# ============================================================

def load_houses():

    con = sqlite3.connect(DB_PATH)

    df = pd.read_sql_query("""
        SELECT *
        FROM houses
        ORDER BY price
    """, con)

    con.close()

    return df


def load_history(fp):

    con = sqlite3.connect(DB_PATH)

    df = pd.read_sql_query("""
        SELECT
            price,
            seen_at
        FROM price_history
        WHERE fingerprint=?
        ORDER BY seen_at
    """, con, params=(fp,))

    con.close()

    return df


df = load_houses()

# ============================================================
# HEADER
# ============================================================

st.title("🏠 新竹雙通勤找房")

st.caption(
    "科環路 × 竹北水瀧三街"
)

st.caption(
    "1000–2000萬｜正2房｜≤20年｜坡道平面｜雙通勤合計≤15km"
)

# ============================================================
# DATA STATUS
# ============================================================

if df.empty:

    st.error("資料庫目前沒有房源。")
    st.stop()

active = df[df["active"] == 1].copy()

# ============================================================
# METRICS
# ============================================================

new_count = len(
    active[active["last_status"] == "new"]
)

drop_count = len(
    active[active["last_status"] == "price_drop"]
)

relisted_count = len(
    active[active["last_status"] == "relisted"]
)

delisted_count = len(
    df[df["active"] == 0]
)

st.subheader("📡 最新追蹤")

a, b, c, d = st.columns(4)

a.metric("🆕 新增", new_count)
b.metric("🔻 降價", drop_count)
c.metric("♻️ 重上架", relisted_count)
d.metric("❌ 下架", delisted_count)

if new_count == 0 and drop_count == 0:
    st.info("本次無新增、無降價")

# ============================================================
# FILTERS
# ============================================================

with st.expander("🔎 篩選", expanded=False):

    price_range = st.slider(
        "總價（萬）",
        500,
        3000,
        (1000, 2000),
        50
    )

    max_age = st.slider(
        "最大屋齡",
        0,
        40,
        20
    )

    max_distance = st.slider(
        "雙通勤合計上限（km）",
        5,
        40,
        15
    )

    districts = st.multiselect(
        "區域",
        [
            "新竹市",
            "竹北市",
            "竹東鎮",
            "寶山鄉",
            "芎林鄉"
        ],
        default=[
            "新竹市",
            "竹北市",
            "竹東鎮",
            "寶山鄉",
            "芎林鄉"
        ]
    )

    strict_parking = st.toggle(
        "只接受明確『坡道平面』",
        True
    )

    strict_distance = st.toggle(
        "只看已驗證且雙通勤≤上限",
        False
    )

# ============================================================
# FILTER
# ============================================================

f = active[
    (active["price"] >= price_range[0])
    &
    (active["price"] <= price_range[1])
    &
    (active["rooms"] == 2)
    &
    (active["age"] <= max_age)
    &
    (active["district"].isin(districts))
].copy()

if strict_parking:
    f = f[f["parking"] == "坡道平面"]

f["distance_total"] = (
    pd.to_numeric(
        f["work1_distance"],
        errors="coerce"
    )
    +
    pd.to_numeric(
        f["work2_distance"],
        errors="coerce"
    )
)

if strict_distance:

    f = f[
        f["distance_total"].notna()
        &
        (f["distance_total"] <= max_distance)
    ]

# ============================================================
# PIPELINE COUNTERS
# ============================================================

st.subheader("🧮 篩選結果")

m1, m2, m3 = st.columns(3)

m1.metric(
    "資料庫",
    f"{len(active):,}"
)

m2.metric(
    "符合基本條件",
    f"{len(f):,}"
)

verified = f[
    f["distance_total"].notna()
]

m3.metric(
    "已驗證距離",
    f"{len(verified):,}"
)

# ============================================================
# MAP
# ============================================================

st.subheader("🗺️ 真實定位房源")

map_df = f[
    f["lat"].notna()
    &
    f["lon"].notna()
].copy()

if not map_df.empty:

    st.map(
        map_df,
        latitude="lat",
        longitude="lon",
        size=50,
        zoom=11,
        height=400
    )

else:

    st.warning(
        "目前沒有完成正式地址定位的物件。"
        "系統不會使用近似座標。"
    )

# ============================================================
# SORT
# ============================================================

sort = st.selectbox(
    "排序",
    [
        "雙通勤距離",
        "價格低 → 高",
        "坪數大 → 小",
        "屋齡新 → 舊"
    ]
)

if sort == "雙通勤距離":

    f = f.sort_values(
        "distance_total",
        na_position="last"
    )

elif sort == "價格低 → 高":

    f = f.sort_values("price")

elif sort == "坪數大 → 小":

    f = f.sort_values(
        "area",
        ascending=False
    )

else:

    f = f.sort_values("age")

# ============================================================
# CARDS
# ============================================================

st.subheader(
    f"🏘️ 房源 ({len(f)})"
)

status_icons = {
    "new": "🆕 新增",
    "price_drop": "🔻 降價",
    "price_up": "🔺 漲價",
    "relisted": "♻️ 重新上架",
    "existing": "👀 追蹤"
}

for _, h in f.iterrows():

    status = status_icons.get(
        h["last_status"],
        "👀 追蹤"
    )

    with st.container(border=True):

        st.markdown(
            f"### {status}｜{h['name']}"
        )

        st.caption(
            f"{h['district']}｜{h['address']}"
        )

        c1, c2 = st.columns(2)

        c1.metric(
            "💰",
            f"{h['price']:,.0f} 萬"
        )

        c2.metric(
            "📐",
            f"{h['area']:.2f} 坪"
        )

        st.write(
            f"**{h['rooms']}房 ｜ "
            f"{h['age']:.1f}年 ｜ "
            f"🚗 {h['parking']}**"
        )

        # -----------------------------------------------
        # DISTANCE
        # -----------------------------------------------

        if pd.notna(h["distance_total"]):

            st.write(
                f"🏭 科環路　"
                f"**{h['work1_distance']:.1f} km**"
            )

            st.write(
                f"🏢 水瀧三街　"
                f"**{h['work2_distance']:.1f} km**"
            )

            if h["distance_total"] <= max_distance:

                st.success(
                    f"🚘 合計 "
                    f"{h['distance_total']:.1f} km ✓"
                )

            else:

                st.error(
                    f"🚘 合計 "
                    f"{h['distance_total']:.1f} km ✕"
                )

        else:

            st.caption(
                "🚘 等待正式地址＋道路距離驗證"
            )

        # -----------------------------------------------
        # HISTORY
        # -----------------------------------------------

        history = load_history(
            h["fingerprint"]
        )

        if len(history) >= 2:

            first = history.iloc[0]["price"]
            latest = history.iloc[-1]["price"]

            diff = latest - first

            if diff < 0:

                pct = abs(diff) / first * 100

                st.success(
                    f"🔻 {first:,.0f} → "
                    f"{latest:,.0f} 萬　"
                    f"-{abs(diff):,.0f}萬 "
                    f"(-{pct:.1f}%)"
                )

            elif diff > 0:

                st.warning(
                    f"🔺 {first:,.0f} → "
                    f"{latest:,.0f} 萬"
                )

        # -----------------------------------------------
        # DATES
        # -----------------------------------------------

        st.caption(
            f"首次：{h['first_seen']}  ｜  "
            f"最新：{h['last_seen']}  ｜  "
            f"{h['source']}"
        )

        # -----------------------------------------------
        # LINK
        # -----------------------------------------------

        if isinstance(h["url"], str) and h["url"]:

            st.link_button(
                "🔗 查看刊登",
                h["url"],
                use_container_width=True
            )

        # -----------------------------------------------
        # PRICE HISTORY
        # -----------------------------------------------

        if not history.empty:

            with st.expander(
                "📈 價格歷史"
            ):

                chart = history.copy()

                chart["seen_at"] = pd.to_datetime(
                    chart["seen_at"]
                )

                chart = chart.set_index(
                    "seen_at"
                )

                st.line_chart(
                    chart["price"]
                )

                st.dataframe(
                    history,
                    hide_index=True,
                    use_container_width=True
                )

# ============================================================
# DELISTED
# ============================================================

delisted = df[
    df["active"] == 0
]

if not delisted.empty:

    with st.expander(
        f"❌ 疑似下架 ({len(delisted)})"
    ):

        st.dataframe(
            delisted[
                [
                    "name",
                    "district",
                    "price",
                    "area",
                    "last_seen"
                ]
            ],
            hide_index=True,
            use_container_width=True
        )

# ============================================================
# SYSTEM STATUS
# ============================================================

st.divider()

st.subheader("⚙️ V5 系統狀態")

st.markdown("""
**已完成**

- 🟢 SQLite 房源資料庫
- 🟢 跨日期房源 fingerprint
- 🟢 新增偵測
- 🟢 降價 / 漲價偵測
- 🟢 重新上架架構
- 🟢 下架架構
- 🟢 價格歷史
- 🟢 CSV 大量匯入
- 🟢 正2房篩選
- 🟢 1000–2000萬篩選
- 🟢 ≤20年篩選
- 🟢 坡道平面 strict mode
- 🟢 雙通勤 ≤15 km 架構
- 🟢 真實座標才畫地圖
- 🟢 手機版 UI

**下一階段**

- 🟡 地址自動驗證
- 🟡 道路距離 API
- 🟡 自動資料來源
- 🟡 GitHub Actions
- 🟡 每日 08:00 / 20:00 更新
""")
