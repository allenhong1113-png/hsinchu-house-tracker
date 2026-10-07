# 新竹雙通勤找房

Streamlit entry point: `App.py`. Install `requirements.txt` (the old `Requirement` redirects to it).

## Data flow

`public search HTML → Sources/source_yungching.py → collector.py → data/houses.csv → import_houses.py → houses.db → App.py`

Run `python collector.py`, `python import_houses.py`, `python -m pytest -q`, then `streamlit run App.py`.
Actions validates the retained real snapshot twice daily at 08:00/20:00 Taiwan time or by manual dispatch. Live refresh is disabled by default after the observed hosted-runner HTTP 403; manually enable it only where source access is permitted. Data is committed only after tests pass. `data/collection_report.json` records actual counts and failed requests.

## Honest scope and filters

This no-key PoC requests one public search page for 新竹市、竹北市、竹東鎮 (including 二重埔)、寶山鄉、芎林鄉. It is not a full market scan. Respect robots.txt, use an identifying User-Agent, sequential requests with >=3 seconds between pages, bounded timeouts, no retry after failed access, no private API, login, cookies or CAPTCHA bypass. Do not infer delisting from missing first-page results.

1000–2000萬, advertised 2 bedrooms, known age <=20, explicit 坡道平面, excluding 綠光森林16. Reject obvious 1+1/2+1/converted rooms and duplex rentals; listing room counts still require floorplan confirmation. Unknown age is not zero. Deduplicate only stable source IDs, never merge separate units by similar size/community.

Final results default to verified road distance total <=15km. Disable the distance toggle to inspect unverified candidates. No guessed house numbers, community/road centroids, or straight-line substitutes. Legacy manual records remain in database history but are excluded from collected counts.

## Distance prerequisites

科環路 and 竹北水瀧三街 identify roads, not unique destination doorways. Exact destination addresses or user-verified entrances are required before any road-distance result can be certified. Current public listing pages usually omit door numbers. Those records stay unlocated and have no map marker. Distance calculation is not yet validated end to end; no distance-qualified listing is claimed by this PoC.

## Review findings

Original collector imported lowercase `sources` but the repository used `Sources`. All errors were swallowed; Actions reported success and imported four existing manual rows. Fixed failure propagation and atomic publication. Shared hash-based importer prevents Streamlit reruns altering seen/status/history. Stable listing IDs tolerate edited titles. No automatic delisting after partial collection. Map requires explicit geocode verification; final list requires road verification.

Tests cover public parser, unknown age, converted rooms, source identity, import idempotence, prices/history, guessed-coordinate rejection, and actual Streamlit rendering of collected candidates. Original `Sources/source_591.py` remains a disabled placeholder, not a working source.

## Runner access limitation observed in Actions

Run #2 returned HTTP 403 for Yungching robots.txt on the hosted runner. Do not evade this restriction. The public HTML snapshot obtained in the development environment is real but is not a successful runner refresh. Collection failure writes `last_collection_attempt.json`; Actions then tests the last successful snapshot with an explicit warning. A green integration run means the App can read real retained data, NOT that a live refresh succeeded. Snapshot provenance remains in `collection_report.json` and each record's `collected_at`. Automatic refresh remains blocked until an allowed data source or permitted runner is available.
