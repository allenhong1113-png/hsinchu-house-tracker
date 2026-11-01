import sqlite3
from pathlib import Path
import pandas as pd
import database
from import_houses import import_csv
from collector import normalize
from Sources.source_yungching import parse_html


def test_public_parser_unknown_age_and_conversion():
    html = '<yc-ng-buy-house-card><a href="house/123"><div class="caseName">三改二房</div><span class="address">新竹縣竹東鎮和江街</span><div class="case-info">--年</div><span class="room">2房(室)2廳1衛</span><span class="car">坡道平面車位</span><div class="price">1,500</div></a></yc-ng-buy-house-card>'
    row = parse_html(html, "https://buy.yungching.com.tw/list/test", "2026-01-01").iloc[0]
    assert row.age is None
    assert row.parking == "坡道平面"
    assert row.layout_status == "excluded_conversion"
    assert row.url.endswith("/house/123")


def test_no_fuzzy_merge():
    df = pd.DataFrame([dict(source="s", listing_id="1", name="same", area=30), dict(source="s", listing_id="2", name="same", area=30)])
    assert len(normalize(df)) == 2


def test_idempotent_import_and_price_history(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    path = tmp_path / "houses.csv"
    row = dict(listing_id="123", source="永慶公開HTML", url="https://buy.yungching.com.tw/house/123", collected_at="2026-01-01", name="A", price=1500, rooms=2, lat=24.8, lon=121.0, work1_distance=1, work2_distance=2)
    pd.DataFrame([row]).to_csv(path, index=False)
    import_csv(path)
    assert import_csv(path) == {"already_imported": True}
    with database.connect() as con:
        assert con.execute("SELECT last_status, lat, work1_distance FROM houses").fetchone()[:] == ("new", None, None)
    row.update(name="new title", price=1400, collected_at="2026-01-02")
    pd.DataFrame([row]).to_csv(path, index=False)
    import_csv(path)
    with database.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM houses").fetchone()[0] == 1
        assert con.execute("SELECT last_status FROM houses").fetchone()[0] == "price_drop"
        assert con.execute("SELECT COUNT(*) FROM price_history").fetchone()[0] == 2


def test_streamlit_reads_collected_data():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(str(Path(__file__).resolve().parent / "App.py"), default_timeout=30).run()
    assert not app.exception
    assert not app.error
    snapshot = pd.read_csv(Path(__file__).resolve().parent / "data" / "houses.csv")
    assert len(snapshot) > 0
    assert int(next(m.value for m in app.metric if m.label == "資料庫").replace(",", "")) == len(snapshot)
    assert snapshot.url.notna().all() and snapshot.collected_at.notna().all()
    # The distance filter must never hide the all-candidate matching audit.
    basic = snapshot[snapshot.price.between(1000,2000) & (snapshot.rooms == 2) & (snapshot.age <= 20) & (snapshot.parking == "坡道平面") & (snapshot.layout_status == "advertised_2_rooms")]
    audit = next(d.value for d in app.dataframe if "處理狀態" in d.value.columns)
    assert set(audit["刊登ID"].astype(str)) == set(basic.listing_id.astype(str))
    assert len(audit) == len(basic)
    from commute_estimates import load_estimates
    valid_routes = load_estimates()
    over = set(audit.loc[audit["處理狀態"].str.contains("（超過上限）", regex=False), "刊登ID"])
    from known_distances import load_known_distances, match_known_distance
    known = load_known_distances()
    effective = {}
    for h in basic.to_dict('records'):
        key = str(h['listing_id'])
        observed = match_known_distance(h, known)
        e = valid_routes.get(key)
        if observed and observed['usable']:
            effective[key] = observed['total']
        elif e and e.get('complete_doors'):
            effective[key] = e['total_max_km']
    assert over == {i for i,total in effective.items() if total > 15}
    # Default cards include every basic candidate; optional final mode excludes unknown routes.
    from commute_estimates import load_estimates
    estimates = load_estimates()
    expected = sum(total <= 15 for total in effective.values())
    assert len(app.get("link_button")) == len(basic)
    assert any(f"房源 ({len(basic)})" in x.value for x in app.subheader)
    app.toggle[1].set_value(True).run()
    assert len(app.get("link_button")) == expected
    app.toggle[2].set_value(False).run()
    assert len(app.get("link_button")) == 0
    assert next(m.value for m in app.metric if m.label == "已驗證距離") == "0"
    app.toggle[1].set_value(False).run()
    assert not app.exception
    assert any("房源 (" in x.value for x in app.subheader)
    assert len(app.get("link_button")) == len(basic)


def test_transaction_doors_require_ministry_record_and_same_street():
    from commute_estimates import parse_transactions
    html = '<article class="deal-card"><p class="deal-card__address">新竹市新竹市埔頂三路30號20樓之7</p><span class="deal-card__date">115年06月</span><p>來源：內政部實價登錄</p></article>'
    rows = parse_transactions(html, "新竹市東區埔頂三路")
    assert rows[0]["proxy_address"] == "新竹市東區埔頂三路30號"
    assert rows[0]["transaction_address"].endswith("20樓之7")
    assert parse_transactions(html, "新竹市東區慈濟路") == []
    assert parse_transactions(html.replace("內政部實價登錄", "永慶房產集團"), "新竹市東區埔頂三路") == []


def test_destination_change_invalidates_estimates(tmp_path):
    import json
    from commute_estimates import load_estimates
    path = tmp_path / "estimates.json"
    path.write_text(json.dumps({"destination_digest": "stale", "rows": [{"listing_id": "1", "status": "estimated_transaction_proxy"}]}))
    assert load_estimates(path) == {}


def test_commute_snapshot_matches_public_provenance():
    import json
    import math
    from commute_estimates import destination_digest
    root = Path(__file__).resolve().parent
    path = root / "data/commute_estimates.json"
    assert path.exists(), "Real road estimate snapshot must be committed before testing"
    estimates = json.loads(path.read_text())
    proxies = json.loads((root / "data/transaction_proxies.json").read_text())
    pins = json.loads((root / "data/transaction_pins.json").read_text())
    listings = pd.read_csv(root / "data/houses.csv", dtype={"listing_id": str}).set_index("listing_id")
    assert estimates["rows"], "No actual road routes were obtained"
    evidence = {r["listing_id"]: r for r in proxies["rows"]}
    assert estimates["destination_digest"] == destination_digest()
    for e in estimates["rows"]:
        h = listings.loc[e["listing_id"]]
        assert h.address == e["listing_address"]
        assert h.collected_at == e["listing_collected_at"]
        assert e["community_url"] == evidence[e["listing_id"]]["community_url"]
        assert e["transaction_url"].startswith(e["community_url"] + "/price")
        assert e["complete_doors"] == (e["door_count"] == e["routed_door_count"])
        totals = []
        for p in e["proxies"]:
            assert p["proxy_address"] in {d["proxy_address"] for d in evidence[e["listing_id"]]["doors"]}
            pin = pins[p["proxy_address"]]
            assert p["lat"] == pin["lat"] and p["lon"] == pin["lon"]
            assert f"!3d{p['lat']}!4d{p['lon']}" in pin["map_url"]
            assert len(p["distances_km"]) == 2
            assert all(math.isfinite(x) and x > 0 for x in p["distances_km"])
            assert all(0 <= x <= 200 for pair in p["road_snap_distances_m"] for x in pair)
            totals.append(sum(p["distances_km"]))
        assert e["total_min_km"] == min(totals)
        assert e["total_max_km"] == max(totals)


def test_all_candidates_have_transaction_match_result():
    import json
    root = Path(__file__).resolve().parent
    snapshot = pd.read_csv(root / "data/houses.csv", dtype={"listing_id": str})
    basic = snapshot[snapshot.price.between(1000,2000) & (snapshot.rooms == 2) & (snapshot.age <= 20) & (snapshot.parking == "坡道平面") & (snapshot.layout_status == "advertised_2_rooms")]
    report = json.loads((root / "data/transaction_proxies.json").read_text())
    assert report["status"] == "complete"
    assert set(report["checked_ids"]) == set(basic.listing_id)
    assert report["checked_listings"] == len(basic)
    outcomes = {r["listing_id"] for r in report["rows"]} | {e["listing_id"] for e in report["errors"]}
    assert outcomes == set(basic.listing_id)
    for r in report["rows"]:
        h = basic.set_index("listing_id").loc[r["listing_id"]]
        assert h.url == r["listing_url"] and h.address == r["listing_address"]
        assert r["transaction_url"].startswith(r["community_url"] + "/price")
        for d in r["doors"]:
            assert "號" in d["proxy_address"] and d["transaction_month"]


"""Offline fixtures and retained observations; no live routing or sale claims."""
import copy
import json
from pathlib import Path
import pandas as pd
from known_distances import load_known_distances, match_known_distance, report_rows


def test_retained_batch_and_address_invalidation():
    known = load_known_distances()
    rows = report_rows(known)
    assert len(rows) == 121
    assert sum(r['合計公里'] is not None for r in rows) == 101
    assert sum(r['距離判定'] == '代理位置≤15公里' for r in rows) == 44
    assert sum(r['距離判定'] == '定位待確認' for r in rows) == 20
    assert all(r['售況'] == '未重新驗證在售' for r in rows)
    for entry in known.values():
        assert match_known_distance(entry, known) is entry
        assert match_known_distance(dict(entry, address='changed'), known) is None
        assert match_known_distance(dict(entry, url='https://example.invalid/changed'), known) is None


def test_changed_destinations_invalidate_all(tmp_path):
    root = Path(__file__).resolve().parent
    (tmp_path/'data').mkdir()
    for name in ['known_property_distances.json', 'destinations.json']:
        (tmp_path/'data'/name).write_text((root/'data'/name).read_text())
    d = json.loads((tmp_path/'data/destinations.json').read_text())
    d['destinations'][0]['lat'] += .001
    (tmp_path/'data/destinations.json').write_text(json.dumps(d))
    assert load_known_distances(tmp_path) == {}


def test_pending_and_invalid_distance_never_pass(tmp_path):
    root = Path(__file__).resolve().parent
    report = json.loads((root/'data/known_property_distances.json').read_text())
    report['route_origins'][0]['distances_km'] = [-1, 1]
    report['route_origins'][1]['distances_km'] = [True, 1]
    report['route_origins'][2]['usable'] = False
    (tmp_path/'data').mkdir()
    (tmp_path/'data/known_property_distances.json').write_text(json.dumps(report))
    (tmp_path/'data/destinations.json').write_text((root/'data/destinations.json').read_text())
    entries = load_known_distances(tmp_path)
    invalid_ids = {r['id'] for r in report['route_origins'][:3]}
    assert all(not e['usable'] and e['total'] is None for e in entries.values() if e['origin_id'] in invalid_ids)


def test_streamlit_displays_batch_and_uses_proxy_filter(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    import database
    monkeypatch.setattr(database, 'DB_PATH', str(tmp_path/'app.db'))
    app = AppTest.from_file(str(Path(__file__).with_name('App.py')), default_timeout=30).run()
    assert not app.exception
    assert any(c.value == '網頁版本：道路距離整合版 2026-11-01' for c in app.caption)
    table = next(t.value for t in app.dataframe if '距離判定' in t.value.columns)
    assert len(table) == 121
    assert len(table[table['距離判定'] == '定位待確認']) == 20
    app.selectbox[0].select('代理位置≤15公里').run()
    assert not app.exception
    table = next(t.value for t in app.dataframe if '距離判定' in t.value.columns)
    assert len(table) == 44
    toggle = next(t for t in app.toggle if t.label == '只看雙通勤≤上限')
    toggle.set_value(True).run()
    assert not app.exception
    assert any('＝' in w.value and 'F12P8' in w.value for w in app.warning)
    assert not any('合計 nan' in w.value for w in app.warning)
