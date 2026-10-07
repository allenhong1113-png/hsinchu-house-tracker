import os
import json
from pathlib import Path
import sqlite3
import pandas as pd
import streamlit as st

from database import init_db, DB_PATH
from import_houses import import_csv, CSV_PATH
from commute_estimates import load_estimates

# ============================================================
# CONFIG
# ============================================================

st.set_page_config(
    page_title="新竹雙通勤找房",
    page_icon="🏠",
    layout="wide"
)

init_db()
# Bootstrap only if CSV content has changed. Never refresh seen/status on UI rerun.
try:
    if CSV_PATH.exists():
        import_csv()
except (ValueError, OSError) as exc:
    st.error(f"房源匯入失敗：{exc}")

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
    "台積電 F12P8 × 竹北半吊子廚房"
)

st.caption(
    "1000–2000萬｜正2房｜≤20年｜坡道平面｜雙通勤合計≤15km"
)

# Destination pins are verified named places, separate from house locations.
destination_path = Path(__file__).resolve().parent / "data/destinations.json"
if destination_path.exists():
    destinations = json.loads(destination_path.read_text())["destinations"]
    with st.expander("📍 通勤目的地（已核對地標）", expanded=True):
        for destination in destinations:
            st.markdown(f"**{destination['name']}** · {destination['address']} · [地圖]({destination['map_url']})")
        pins = [d for d in destinations if d.get("geocode_status") == "verified_place_pin"]
        if pins:
            st.map(pd.DataFrame(pins)[["lat", "lon"]])
        st.caption("目的地使用已核對的地標點位；依指定地標計算，不核對車行出入口。可使用同社區實價門牌作估算，結果會分開標示。")

# ============================================================
# DATA STATUS
# ============================================================

if df.empty:

    st.error("資料庫目前沒有房源。")
    st.stop()

active = df[(df["active"] == 1) & df["listing_id"].notna() & df["collected_at"].notna()].copy()
# Legacy rows lacking listing URLs are retained in history but are not collected listings.
st.caption("筆數按不同刊登ID計算；同社區、樓層、坪數相同者可能為重複刊登，尚未確認是否同一戶。")
st.info("公開房源 PoC：各區第一頁，並非全市場掃描。同社區實價門牌可作道路距離估算，不代表待售戶的確切門牌。正2房仍須核對格局圖。")

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
        "只看雙通勤≤上限",
        True
    )

    allow_estimates = st.toggle("允許同社區實價門牌估算", True)

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

f = f[~(f["name"].fillna("") + f["title"].fillna("")).str.replace(" ", "", regex=False).str.contains("綠光森林16", regex=False)]
f = f[f["layout_status"] == "advertised_2_rooms"]
basic_count = len(f[f["parking"] == "坡道平面"])

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

# Snapshot estimates are bound to both the listing street/date and destinations.
estimates = load_estimates()
f["estimate"] = [estimates.get(str(x)) for x in f["listing_id"]]
f["estimate"] = [e if isinstance(e, dict) and e.get("listing_address") == a and e.get("listing_collected_at") == t else None for e, a, t in zip(f["estimate"], f["address"], f["collected_at"])]
f["distance_kind"] = "unverified"
for index, h in f.iterrows():
    if h["route_status"] == "verified_road" and pd.notna(h["distance_total"]):
        f.at[index, "distance_kind"] = "verified_road"
    elif allow_estimates and isinstance(h["estimate"], dict):
        e = h["estimate"]
        # Unlocated transaction doors remain uncertain and cannot pass the final filter.
        if e.get("complete_doors"):
            f.at[index, "distance_total"] = e["total_max_km"]
            f.at[index, "distance_kind"] = "estimated_transaction_proxy"

estimated_count = int((f["distance_kind"] == "estimated_transaction_proxy").sum())
if strict_distance:
    f = f[(f["distance_kind"] != "unverified") & f["distance_total"].notna() & (f["distance_total"] <= max_distance)]

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
    f"{basic_count:,}"
)

verified = f[
    (f["route_status"] == "verified_road") & f["distance_total"].notna()
]

m3.metric(
    "已驗證距離",
    f"{len(verified):,}"
)

st.caption(f"已完成同社區實價門牌估算：{estimated_count} 筆基本條件房源。估算採已取得門牌中的最大合計；不是確切待售戶定位，也不是完整社區範圍。")

# ============================================================
# MAP
# ============================================================

st.subheader("🗺️ 真實定位房源")

map_df = f[
    (f["geocode_status"] == "verified_address")
    & f["lat"].notna()
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
        "未定位的地址不標示。"
    )

proxy_pins = []
for e in f["estimate"]:
    if allow_estimates and isinstance(e, dict):
        for p in e["proxies"]:
            if p.get("status") == "reviewed_exact_door_pin":
                proxy_pins.append({"lat": p["lat"], "lon": p["lon"], "門牌": p["proxy_address"]})
if proxy_pins:
    st.subheader("📍 實價門牌估算位置（非待售戶確址）")
    st.map(pd.DataFrame(proxy_pins).drop_duplicates("門牌"), latitude="lat", longitude="lon")
    st.caption("只標示已核對的實價門牌地圖點位；沒有使用街道中心、社區中心或猜測座標。")

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

        if h["route_status"] == "verified_road" and pd.notna(h["distance_total"]):

            st.write(
                f"🏭 台積電 F12P8　"
                f"**{h['work1_distance']:.1f} km**"
            )

            st.write(
                f"🏢 半吊子廚房　"
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

        elif allow_estimates and isinstance(h["estimate"], dict):
            e = h["estimate"]
            st.warning(f"實價門牌估算：雙通勤合計 {e['total_min_km']:.2f}–{e['total_max_km']:.2f} km（非待售戶確址）")
            if not e["complete_doors"]:
                st.caption(f"僅 {e['routed_door_count']}/{e['door_count']} 個已取得門牌完成定位；不列入≤上限結果。")
            for p in e["proxies"]:
                st.write(f"{p['proxy_address']}：F12P8 {p['distances_km'][0]:.2f} km ＋ 半吊子廚房 {p['distances_km'][1]:.2f} km")
                st.caption(f"實價紀錄：{p['transaction_address']} · {p['transaction_month']}")
                st.markdown(f"[核對門牌地圖]({p['map_url']})")
            st.markdown(f"[同社區實價門牌來源]({e['transaction_url']})")
            st.caption("OSRM 汽車路線的道路距離；不考慮即時路況、車行入口。© OpenStreetMap contributors（ODbL）／FOSSGIS。")
        else:
            st.caption("🚘 尚無可核對的實價門牌定位／道路距離")

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

st.subheader("⚙️ 公開資料 PoC 狀態")
report_path = Path(__file__).resolve().parent / "data/collection_report.json"
if report_path.exists():
    st.json(json.loads(report_path.read_text()))
st.caption("未使用付費 API key。確切房源與實價門牌估算位置分開顯示，不使用路中心或社區中心猜測。部分頁面抓取不推斷下架。")
st.markdown("[道路服務使用規則](https://routing.openstreetmap.de/about.html) · [回報道路問題](https://www.openstreetmap.org/fixthemap)")
attempt_path = Path(__file__).resolve().parent / "data/last_collection_attempt.json"
if attempt_path.exists():
    attempt = json.loads(attempt_path.read_text())
    if attempt.get("status") != "success":
        st.warning("最新自動抓取失敗；目前顯示上次成功取得的房源快照，不代表本次有取得新資料。")
        st.json(attempt)
