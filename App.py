import os
import json
from pathlib import Path
import sqlite3
import pandas as pd
import streamlit as st

from database import init_db, DB_PATH
from import_houses import import_csv, CSV_PATH
from commute_estimates import load_estimates
from known_distances import load_known_distances, match_known_distance, report_rows
from listing_validation import load_checks, row_check

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

# Offline road observations are read on every rerun, independent of DB import.
st.caption("網頁版本：道路距離整合版 2026-11-01")
try:
    known_distances = load_known_distances()
except (ValueError, OSError, KeyError, TypeError) as exc:
    known_distances = {}
    st.warning(f"整批距離資料暫時無法讀取：{exc}")
if known_distances:
    with st.expander("完整已知房源道路距離（含591、愛屋網紀錄）", expanded=True):
        known_df = pd.DataFrame(report_rows(known_distances))
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("已知刊登紀錄", len(known_df))
        k2.metric("可用代理距離", int(known_df["合計公里"].notna().sum()))
        k3.metric("代理位置≤15公里", int((known_df["距離判定"] == "代理位置≤15公里").sum()))
        k4.metric("定位待確認", int(known_df["合計公里"].isna().sum()))
        st.caption("本表涵蓋整批已知刊登，不套用下方基本條件篩選。距離採社區或同社區成交門牌代理，非實際戶別；售況未重新驗證。定位待確認不納入≤15公里。")
        known_view = st.selectbox("整批距離表顯示", ["全部紀錄", "代理位置≤15公里", "超過15公里", "定位待確認"])
        shown_known = known_df if known_view == "全部紀錄" else known_df[known_df["距離判定"] == known_view]
        st.dataframe(shown_known, hide_index=True, use_container_width=True)
        st.download_button("下載完整已知房源距離", known_df.to_csv(index=False).encode("utf-8-sig"), file_name="known-property-distances.csv", mime="text/csv")

# ============================================================
# DATA STATUS
# ============================================================

if df.empty:

    st.error("資料庫目前沒有房源。")
    st.stop()

active = df[(df["active"] == 1) & df["listing_id"].notna() & df["collected_at"].notna()].copy()
# Legacy rows lacking listing URLs are retained in history but are not collected listings.
st.caption("筆數按不同刊登ID計算；同社區、樓層、坪數相同者可能為重複刊登，尚未確認是否同一戶。")
st.info("搜尋涵蓋各區可存取的公開分頁；實際覆蓋率見下方報告。保留紀錄不代表本次確認在售；同社區實價門牌的道路距離是估算，正2房仍須核對格局圖。")
root = Path(__file__).resolve().parent
checks = load_checks(root / 'data/listing_checks.json', root / 'data/last_collection_attempt.json')
active['availability'] = [row_check(h, checks)['status'] for h in active.to_dict('records')]
active['availability_checked_at'] = [row_check(h, checks)['checked_at'] for h in active.to_dict('records')]
st.caption(f"本次24小時內逐筆確認刊登頁顯示在售：{int((active['availability'] == 'verified_available').sum())} 筆；其餘為待確認或無法存取。")

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
        15,
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
        False,
        key="strict_distance_candidates_v2",
        help="預設保留待定位與超過距離的刊登；開啟後只保留已有道路距離且符合上限的結果。"
    )

    allow_estimates = st.toggle("允許社區地標／實價門牌估算", True)
    only_available = st.toggle("只看本次已確認刊登頁在售", False)

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
basic_candidates = f[f["parking"] == "坡道平面"].copy()

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
f["known_distance"] = [match_known_distance(h, known_distances) for h in f.to_dict("records")]
f["distance_kind"] = "unverified"
for index, h in f.iterrows():
    if h["route_status"] == "verified_road" and pd.notna(h["distance_total"]):
        f.at[index, "distance_kind"] = "verified_road"
    elif allow_estimates and isinstance(h["known_distance"], dict) and h["known_distance"]["usable"]:
        f.at[index, "distance_total"] = h["known_distance"]["total"]
        f.at[index, "distance_kind"] = "estimated_community_proxy"
    elif allow_estimates and isinstance(h["estimate"], dict):
        e = h["estimate"]
        # Unlocated transaction doors remain uncertain and cannot pass the final filter.
        if e.get("complete_doors"):
            f.at[index, "distance_total"] = e["total_max_km"]
            f.at[index, "distance_kind"] = "estimated_transaction_proxy"

estimated_count = int(f["distance_kind"].isin(["estimated_transaction_proxy", "estimated_community_proxy"]).sum())
if strict_distance:
    f = f[(f["distance_kind"] != "unverified") & f["distance_total"].notna() & (f["distance_total"] <= max_distance)]

if only_available:
    f = f[f["availability"] == "verified_available"]

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

st.caption(f"已完成社區地標／實價門牌估算：{estimated_count} 筆目前條件房源。新整批道路觀測優先使用，舊門牌快取取最大合計；均非確切待售戶定位。")

# Every basic candidate remains visible in the audit table, even when the distance
# filter hides its card. A missing route is pending, never over the limit.
proxy_report_path = Path(__file__).resolve().parent / "data/transaction_proxies.json"
proxy_report = json.loads(proxy_report_path.read_text()) if proxy_report_path.exists() else {"rows": [], "errors": []}
proxy_rows = {r["listing_id"]: r for r in proxy_report["rows"]}
proxy_errors = {r["listing_id"]: r for r in proxy_report.get("errors", []) if r.get("listing_id")}
pin_path = Path(__file__).resolve().parent / "data/transaction_pins.json"
reviewed_pins = json.loads(pin_path.read_text()) if pin_path.exists() else {}
audit_rows = []
matched_count = 0
for _, h in basic_candidates.iterrows():
    listing_id = str(h["listing_id"])
    evidence = proxy_rows.get(listing_id)
    if evidence and (evidence.get("listing_address") != h["address"] or evidence.get("listing_collected_at") != h["collected_at"]):
        evidence = None
    doors = evidence.get("doors", []) if evidence else []
    status = "尚未比對"
    error = proxy_errors.get(listing_id)
    if error:
        status = error.get("detail", error.get("reason", "比對尚未完成"))
    if evidence:
        status = "已取得實價門牌，待定位與道路計算" if doors else "公開實價頁尚無同街明確門牌"
    if doors:
        matched_count += 1
        rejected = [p["proxy_address"] for p in doors if reviewed_pins.get(p["proxy_address"], {}).get("status", "").startswith("rejected_")]
        if rejected:
            status = "已取得門牌，但地圖定位不明確"
    e = estimates.get(listing_id)
    if e and e.get("listing_address") == h["address"] and e.get("listing_collected_at") == h["collected_at"]:
        if e.get("complete_doors"):
            status = f"已完成門牌估算：{e['total_max_km']:.2f} km" + ("（≤上限）" if e["total_max_km"] <= max_distance else "（超過上限）")
        else:
            status = "部分門牌完成路線，其他門牌待定位"
    known = match_known_distance(h, known_distances)
    if known:
        status = (f"已完成代理道路估算：{known['total']:.2f} km" + ("（≤上限）" if known['total'] <= max_distance else "（超過上限）")) if known["usable"] else "定位待確認：" + known["origin"].get("note", "")
    audit_rows.append({"刊登ID": listing_id, "社區／刊登名稱": h["name"], "總價（萬）": h["price"], "刊登街名": h["address"], "原始頁驗證": h["availability"], "驗證時間": h["availability_checked_at"], "實價門牌": "、".join(p["proxy_address"] for p in doors), "處理狀態": status, "實價來源": evidence.get("transaction_url", "") if evidence else (error.get("alternative_transaction_url", "") if error else ""), "刊登網址": h["url"]})
with st.expander(f"📋 全部基本條件刊登的實價門牌比對 ({len(audit_rows)})", expanded=True):
    st.caption(f"已取得門牌 {matched_count}/{len(audit_rows)} 筆。待定位或待路線計算不代表超過15公里；下方距離篩選不會隱藏本表。")
    audit_df = pd.DataFrame(audit_rows)
    st.dataframe(audit_df, hide_index=True, use_container_width=True)
    st.download_button("下載全部門牌比對結果", audit_df.to_csv(index=False).encode("utf-8-sig"), file_name="transaction-door-matches.csv", mime="text/csv")

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
st.caption("目前只顯示已算出距離且符合上限的刊登；可展開上方「🔎 篩選」關閉『只看雙通勤≤上限』查看全部基本條件刊登。" if strict_distance else "目前顯示全部基本條件刊登；其中包含待定位、待道路計算與超過距離上限的物件，並非全部符合雙通勤條件。")
audit_by_id = {r["刊登ID"]: r for r in audit_rows}

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
        availability_labels = {
            'verified_available': '已核對原始頁身分、價格／坪數與看屋入口，頁面顯示在售',
            'unavailable_http': '原始頁已無法開啟（404／410）；保留歷史，不確認在售',
            'explicitly_offmarket': '原始頁明示已下架／成交；保留歷史',
            'not_verified_this_run': '本次尚未驗證；不確認在售',
        }
        st.warning('原始刊登驗證：' + availability_labels.get(h['availability'], '未能確認：' + h['availability']))
        if h['availability_checked_at']:
            st.caption('原始頁檢查時間：' + str(h['availability_checked_at']))
        match = audit_by_id.get(str(h["listing_id"]))
        if match:
            st.info(f"門牌／距離狀態：{match['處理狀態']}")

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

        elif allow_estimates and isinstance(h["known_distance"], dict) and h["known_distance"]["usable"]:
            known = h["known_distance"]
            origin = known["origin"]
            legs = origin["distances_km"]
            st.warning(f"{origin['level']}：F12P8 {legs[0]:.2f} km ＋ 半吊子廚房 {legs[1]:.2f} km ＝ {known['total']:.2f} km（非待售戶確址）")
            st.caption(f"代理起點：{origin['used_origin']}。{origin.get('note', '')}")
            st.caption(f"道路來源：{origin['provider']}；計算時間：{origin['checked_at']}")
            for label, url in zip(["F12P8路線／快取地標", "半吊子路線／快取地標"], origin.get("route_urls", [])):
                st.markdown(f"[{label}]({url})")
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
            if match and match["實價門牌"]:
                st.write(f"已取得實價門牌：{match['實價門牌']}")
            if match and match["實價來源"]:
                st.markdown(f"[查看實價來源（門牌尚待定位或核對）]({match['實價來源']})")

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

        if isinstance(h["url"], str) and h["url"] and h["availability"] not in ("unavailable_http", "explicitly_offmarket"):

            st.link_button(
                "🔗 查看刊登" if h["availability"] == "verified_available" else "🔗 原始連結（尚未確認在售）",
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
st.caption("未使用付費 API key。Google Maps 駕車建議路線與既有 OSRM 快取均標示來源；社區代理距離與確址驗證分開。街道參考與期別不符不納入距離合格，部分頁面抓取不推斷下架。")
st.markdown("[道路服務使用規則](https://routing.openstreetmap.de/about.html) · [回報道路問題](https://www.openstreetmap.org/fixthemap)")
attempt_path = Path(__file__).resolve().parent / "data/last_collection_attempt.json"
if attempt_path.exists():
    attempt = json.loads(attempt_path.read_text())
    if attempt.get("status") != "success":
        st.warning("最新搜尋為部分完成或失敗；已保留成功資料與歷史。各區覆蓋率及逐筆在售驗證應分別檢查。")
        st.json(attempt)
