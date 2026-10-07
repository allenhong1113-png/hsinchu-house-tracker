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
    assert int(app.metric[4].value.replace(",", "")) == len(snapshot)
    assert snapshot.url.notna().all() and snapshot.collected_at.notna().all()
    # Candidate mode renders actual listing links, while final mode excludes unknown routes.
    from commute_estimates import load_estimates
    estimates = load_estimates()
    expected = sum(e.get("complete_doors") and e["total_max_km"] <= 15 for e in estimates.values())
    assert len(app.get("link_button")) == expected
    app.toggle[2].set_value(False).run()
    assert len(app.get("link_button")) == 0
    assert app.metric[6].value == "0"
    app.toggle[1].set_value(False).run()
    assert not app.exception
    assert any("房源 (" in x.value for x in app.subheader)
    assert len(app.get("link_button")) > 0


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
