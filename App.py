import streamlit as st
import pandas as pd

st.set_page_config(
    page_title="新竹雙通勤找房",
    page_icon="🏠",
    layout="wide"
)

st.title("🏠 新竹雙通勤找房")
st.caption("科環路 × 竹北水瀧三街")

st.success("系統已成功啟動！")

st.subheader("目前搜尋條件")

col1, col2 = st.columns(2)

with col1:
    st.metric("最低總價", "1,000 萬")
    st.metric("房數", "2 房")
    st.metric("最大屋齡", "20 年")

with col2:
    st.metric("最高總價", "2,000 萬")
    st.metric("車位", "坡道平面")
    st.metric("雙通勤合計", "≤ 15 km")

st.divider()

st.subheader("📊 房源資料")

data = {
    "社區": [
        "測試物件 A",
        "測試物件 B",
        "測試物件 C"
    ],
    "總價(萬)": [1698, 1798, 1528],
    "坪數": [38.2, 38.3, 34.8],
    "科環路(km)": [5.8, 6.2, 5.1],
    "水瀧三街(km)": [4.9, 3.1, 11.8]
}

df = pd.DataFrame(data)

df["合計距離(km)"] = (
    df["科環路(km)"] +
    df["水瀧三街(km)"]
)

df = df.sort_values("合計距離(km)")

st.dataframe(
    df,
    use_container_width=True,
    hide_index=True
)

st.divider()

st.info(
    "下一階段：接入真實房源資料、去重、"
    "坡道平面辨識、價格歷史與地圖。"
)
