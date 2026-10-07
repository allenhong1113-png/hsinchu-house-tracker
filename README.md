# 新竹雙通勤找房

Streamlit entry point: `App.py`. Install `requirements.txt` (the old `Requirement` redirects to it).

## Data flow

`public search HTML → Sources/source_yungching.py → collector.py → data/houses.csv → import_houses.py → houses.db → App.py`

Run `python collector.py`, `python import_houses.py`, `python -m pytest -q`, then `streamlit run App.py`.
Actions validates the retained real snapshot twice daily at 08:00/20:00 Taiwan time or by manual dispatch. Live refresh is disabled by default after the observed hosted-runner HTTP 403; manually enable it only where source access is permitted. Data is committed only after tests pass. `data/collection_report.json` records actual counts and failed requests.

## Honest scope and filters

This no-key PoC requests one public search page for 新竹市、竹北市、竹東鎮 (including 二重埔)、寶山鄉、芎林鄉. It is not a full market scan. Respect robots.txt, use an identifying User-Agent, sequential requests with >=3 seconds between pages, bounded timeouts, no retry after failed access, no private API, login, cookies or CAPTCHA bypass. Do not infer delisting from missing first-page results.

1000–2000萬, advertised 2 bedrooms, known age <=20, explicit 坡道平面, excluding 綠光森林16. Reject obvious 1+1/2+1/converted rooms and duplex rentals; listing room counts still require floorplan confirmation. Unknown age is not zero. Deduplicate only stable source IDs, never merge separate units by similar size/community.

Final results default to road distance total <=15km, allowing clearly labelled same-community transaction-door estimates as requested. Disable the estimate toggle to require exact-house verified routes. Disable the distance toggle to inspect unverified candidates. No guessed house numbers, community/road centroids, or straight-line substitutes. Legacy manual records remain in database history but are excluded from collected counts.

## Distance prerequisites

Destinations are now configured in `data/destinations.json`: 台積電全球研發中心 (F12P8), 寶山鄉科環路168號, and 半吊子廚房, 竹北市中山路52巷5號. Addresses were checked against the TSMC/company-registration sources and the bakery website, and Google Maps place pins were checked in the browser. Coordinates come from the place URL's !3d/!4d fields, never the map viewport. These are verified named-place pins, not individually verified vehicle entrances. The App displays destination pins separately from house markers. Public listings still omit house numbers. Per the requested method, explicitly linked community transaction door numbers can serve as location proxies. Vehicle entrances are intentionally ignored. Exact house verification is distinct from an estimate.

## Review findings

Original collector imported lowercase `sources` but the repository used `Sources`. All errors were swallowed; Actions reported success and imported four existing manual rows. Fixed failure propagation and atomic publication. Shared hash-based importer prevents Streamlit reruns altering seen/status/history. Stable listing IDs tolerate edited titles. No automatic delisting after partial collection. Exact-house map markers require explicit address verification. Separate estimate markers require a reviewed exact transaction-door pin. Final estimates require all doors obtained in that sampled community page to be located and routed; use their maximum combined distance. This is not a guarantee for other doors or the exact sale unit.

Tests cover public parser, unknown age, converted rooms, source identity, import idempotence, prices/history, guessed-coordinate rejection, and actual Streamlit rendering of collected candidates. Original `Sources/source_591.py` remains a disabled placeholder, not a working source.

## Runner access limitation observed in Actions

Run #2 returned HTTP 403 for Yungching robots.txt on the hosted runner. Do not evade this restriction. The public HTML snapshot obtained in the development environment is real but is not a successful runner refresh. Collection failure writes `last_collection_attempt.json`; Actions then tests the last successful snapshot with an explicit warning. A green integration run means the App can read real retained data, NOT that a live refresh succeeded. Snapshot provenance remains in `collection_report.json` and each record's `collected_at`. Automatic refresh remains blocked until an allowed data source or permitted runner is available.

## 實價門牌估算 PoC

`python commute_estimates.py discover` 讀取房源本身的地址欄或詳細資料欄公開社區連結，再讀該社區公開實價頁第一頁。每筆結果原子保存，可續跑；404及單筆5xx不會中斷其餘刊登，401/403/429等存取限制仍停止。`--retry-unmatched` 可明確重試未比對紀錄。僅取來源標為「內政部實價登錄」、且街名符合房源的門牌；樓層另存原始實價地址，不把成交戶當作待售戶。`data/transaction_proxies.json` 保留房源網址、社區網址、成交月份及門牌證據。目前針對全部53筆基本條件刊登逐筆處理。報告的 `checked_ids` 列出每筆檢查結果，`rows` 保存已取得門牌，`errors` 保存缺少連結、404、服務異常等原因。不是完整社區或市場掃描；有門牌仍須另行定位、道路計算。

`data/transaction_pins.json` 記錄逐一在地圖確認的門牌點位與來源網址（!3d/!4d，不用視窗中心）。延平路二段1428號搜尋回傳1428–1430號範圍，已拒絕該定位，沒有填猜測座標或距離。

`python commute_estimates.py calculate` 以免費、免 key 的 FOSSGIS OSRM 汽車路線計算 **房源實價門牌 → F12P8** 與 **房源實價門牌 → 半吊子廚房**。單線序列請求間隔超過1秒、同門牌快取共用、道路吸附限制200公尺，無即時交通資訊。遵守 [服務規則](https://routing.openstreetmap.de/about.html)，資料 © OpenStreetMap contributors／ODbL；可 [回報道路問題](https://www.openstreetmap.org/fixthemap)。沒有內建公共 Nominatim 通用定位 API，也沒有付費 API key。

結果存入 `data/commute_estimates.json`，不覆蓋原房源的精確地址／座標／驗證距離。Streamlit 以房源 ID、街名、取得時間及目的地座標摘要檢查快照，目的地改變即失效。估算顯示每個實價門牌的兩段距離與合計範圍；≤15公里的估算結果仍須確認待售戶正2房格局，不宣稱確切待售戶已驗證。Actions 實際執行快照與 Streamlit 整合測試，並保留門牌、點位及距離 artifacts；不宣稱 hosted runner 取得新房源。

App 新增「全部基本條件刊登的實價門牌比對」表及 CSV 下載：即使道路距離篩選只留下3筆，表中仍保留全部53筆的實價門牌及處理狀態。未定位、網站失效與超過15公里分開顯示；不能用尚未算出距離來判定不合格。已取得的道路距離按目的地摘要及門牌點位快取，目的地或點位變更才重新請求。
