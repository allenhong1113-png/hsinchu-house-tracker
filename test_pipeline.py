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
    app = AppTest.from_file(str(Path(__file__).resolve().parent / "App.py")).run(timeout=30)
    assert not app.exception
    assert not app.error
    assert int(app.metric[4].value.replace(",", "")) > 0
    # Candidate mode renders actual listing links, while final mode excludes unknown routes.
    assert len(app.get("link_button")) == 0
    app.toggle[1].set_value(False).run()
    assert not app.exception
    assert any("房源 (" in x.value for x in app.subheader)
    assert len(app.get("link_button")) > 0
