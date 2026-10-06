import streamlit as st
import pandas as pd
from datetime import datetime

# =========================================================
# APP CONFIG
# =========================================================

st.set_page_config(
    page_title="新竹雙通勤找房",
    page_icon="🏠",
    layout="wide"
)

# =========================================================
# SAMPLE / CURRENT TRACKING DATABASE
# 下一版會改成 CSV / SQLite 自動更新
# =========================================================

houses = [
    {
        "status": "🔻 降價",
        "name": "佳陞禾樂",
        "district": "竹北市",
        "address": "新竹縣竹北市光明十五街",
        "price": 1728,
        "old_price": 1798,
        "area": 37.34,
        "age": 4.2,
        "rooms": 2,
        "parking": "坡道平面",
        "work1": 0.0,
        "work2": 0.0,
        "source": "永慶",
        "url": "",
        "first_seen": "2026-10-06",
        "last_seen": "2026-10-07",
        "lat": None,
        "lon": None,
    },
    {
        "status": "🔻 降價",
        "name": "星都匯 D區",
        "district": "竹東鎮",
        "address": "新竹縣竹東鎮旭光一路",
        "price": 1528,
        "old_price": 1598,
        "area": 34.78,
        "age": 0.3,
        "rooms": 2,
        "parking": "坡道平面",
        "work1": 0.0,
        "work2": 0.0,
        "source": "永慶",
        "url": "",
        "first_seen": "2026-10-05",
        "last_seen": "2026-10-07",
        "lat": None,
        "lon": None,
    },
    {
        "status": "🔻 降價",
        "name": "臻研臻美",
        "district": "竹東鎮",
        "address": "新竹縣竹東鎮和江街",
        "price": 1398,
        "old_price": 1498,
        "area": 41.39,
        "age": 10.8,
        "rooms": 2,
        "parking": "坡道平面",
        "work1": 0.0,
        "work2": 0.0,
        "source": "永慶",
        "url": "",
        "first_seen": "2026-10-06",
        "last_seen": "2026-10-07",
        "lat": None,
        "lon": None,
    },
    {
        "status": "👀 追蹤",
        "name": "美學苑",
        "district": "新竹市",
        "address": "新竹市北區經國路二段",
        "price": 1398,
        "old_price": 1398,
        "area": 32.88,
        "age": 19.8,
        "rooms": 2,
        "parking": "坡道平面",
        "work1": 0.0,
        "work2": 0.0,
        "source": "房仲",
        "url": "",
        "first_seen": "2026-09-29",
        "last_seen": "2026-10-07",
        "lat": None,
        "lon": None,
    },
    {
        "status": "👀 追蹤",
        "name": "竹科潤隆",
        "district": "新竹市",
        "address": "新竹市東區埔頂三路30號",
        "price": 1986,
        "old_price": 1986,
        "area": 31.25,
        "age": 3.3,
        "rooms": 2,
        "parking": "坡道平面",
        "work1": 0.0,
        "work2": 0.0,
        "source": "房仲",
        "url": "",
        "first_seen": "2026-10-02",
        "last_seen": "2026-10-07",
        "lat": None,
        "lon": None,
    },
]

df = pd.DataFrame(houses)

# =========================================================
# HEADER
# =========================================================

st.title("🏠 新竹雙通勤找房")

st.caption(
    "📍 科環路 × 竹北水瀧三街 ｜ "
    "1000–2000萬 ｜ 正2房 ｜ ≤20年 ｜ 坡道平面"
)

st.caption(
    f"最後更新：{datetime.now().strftime('%Y-%m-%d %H:%M')}"
)

# =========================================================
# FILTER
# =========================================================

with st.expander("🔎 搜尋條件", expanded=False):

    price_range = st.slider(
        "總價（萬）",
        500,
        3000,
        (1000, 2000),
        step=50
    )

    age_limit = st.slider(
        "最大屋齡",
        0,
        40,
        20
    )

    distance_limit = st.slider(
        "雙通勤合計距離（km）",
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

# =========================================================
# APPLY FILTER
# =========================================================

filtered = df[
    (df["price"] >= price_range[0]) &
    (df["price"] <= price_range[1]) &
    (df["age"] <= age_limit) &
    (df["rooms"] == 2) &
    (df["parking"] == "坡道平面") &
    (df["district"].isin(districts))
].copy()

# 只有距離已經計算的才使用15km硬篩
filtered["distance_total"] = filtered["work1"] + filtered["work2"]

# =========================================================
# SUMMARY
# =========================================================

st.subheader("📊 本次追蹤")

c1, c2, c3 = st.columns(3)

c1.metric(
    "追蹤房源",
    len(filtered)
)

c2.metric(
    "降價",
    len(filtered[filtered["price"] < filtered["old_price"]])
)

c3.metric(
    "新物件",
    len(filtered[filtered["status"].str.contains("新增")])
)

# =========================================================
# PRICE CHANGES
# =========================================================

changes = filtered[
    filtered["price"] < filtered["old_price"]
]

if len(changes) > 0:

    st.success(
        f"🔥 發現 {len(changes)} 筆降價房源"
    )

else:

    st.info(
        "本次無新增、無降價"
    )

# =========================================================
# MAP
# =========================================================

st.subheader("🗺️ 房源地圖")

map_df = filtered[
    filtered["lat"].notna() &
    filtered["lon"].notna()
][["lat", "lon"]]

if len(map_df) > 0:

    st.map(
        map_df,
        latitude="lat",
        longitude="lon",
        zoom=11,
        height=380
    )

else:

    st.warning(
        "目前尚未有通過正式地址定位驗證的座標。"
        "為避免錯誤標記，本版不使用近似位置。"
    )

# =========================================================
# SORT
# =========================================================

sort_option = st.selectbox(
    "排序方式",
    [
        "價格低 → 高",
        "坪數大 → 小",
        "屋齡新 → 舊",
        "降價幅度"
    ]
)

if sort_option == "價格低 → 高":
    filtered = filtered.sort_values("price")

elif sort_option == "坪數大 → 小":
    filtered = filtered.sort_values(
        "area",
        ascending=False
    )

elif sort_option == "屋齡新 → 舊":
    filtered = filtered.sort_values("age")

else:
    filtered["drop"] = (
        filtered["old_price"] -
        filtered["price"]
    )

    filtered = filtered.sort_values(
        "drop",
        ascending=False
    )

# =========================================================
# MOBILE CARDS
# =========================================================

st.subheader("🏘️ 房源")

for _, h in filtered.iterrows():

    drop = h["old_price"] - h["price"]

    with st.container(border=True):

        st.markdown(
            f"### {h['status']}｜{h['name']}"
        )

        st.caption(
            f"{h['district']} ｜ "
            f"{h['address']}"
        )

        a, b = st.columns(2)

        a.metric(
            "💰 總價",
            f"{h['price']:,} 萬"
        )

        b.metric(
            "🏠 坪數",
            f"{h['area']:.2f} 坪"
        )

        st.write(
            f"**2房 ｜ {h['age']}年 ｜ "
            f"🚗 {h['parking']}**"
        )

        # Price change
        if drop > 0:

            pct = drop / h["old_price"] * 100

            st.success(
                f"🔻 {h['old_price']:,} → "
                f"{h['price']:,} 萬　"
                f"降 {drop:,} 萬 "
                f"({pct:.1f}%)"
            )

        # Distance
        if h["work1"] > 0 and h["work2"] > 0:

            total = h["work1"] + h["work2"]

            st.write(
                f"🏭 科環路：**{h['work1']:.1f} km**"
            )

            st.write(
                f"🏢 水瀧三街：**{h['work2']:.1f} km**"
            )

            if total <= distance_limit:

                st.success(
                    f"🚘 雙通勤合計："
                    f"**{total:.1f} km ✓**"
                )

            else:

                st.error(
                    f"🚘 雙通勤合計："
                    f"**{total:.1f} km ✕**"
                )

        else:

            st.caption(
                "🚘 雙通勤道路距離：等待正式地址驗證"
            )

        st.caption(
            f"首次發現：{h['first_seen']} ｜ "
            f"最新追蹤：{h['last_seen']} ｜ "
            f"來源：{h['source']}"
        )

        if h["url"]:

            st.link_button(
                "🔗 查看原始房源",
                h["url"],
                use_container_width=True
            )

# =========================================================
# DATABASE STATUS
# =========================================================

st.divider()

st.subheader("🗄️ 資料庫狀態")

st.write(
    """
    🟢 App：正常  
    🟢 條件篩選：正常  
    🟢 價格比較：正常  
    🟢 手機卡片：正常  
    🟡 正式地址定位：下一階段  
    🟡 雙通勤道路距離：下一階段  
    🟡 大量房源資料庫：下一階段  
    🔴 自動爬取：尚未接入
    """
)

st.caption(
    "定位失敗的房源不會顯示錯誤 Marker。"
)
