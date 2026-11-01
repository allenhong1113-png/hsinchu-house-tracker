"""Synthetic network fixtures only; none of these distances/listings are real data."""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
import pytest
import requests
import collector
import database
import commute_estimates as routes
from import_houses import import_csv
from Sources import source_yungching as source
from listing_validation import classify_detail, verify_listings, load_checks, row_check


def card(listing_id, address='新竹縣竹東鎮二重埔'):
    return f'<yc-ng-buy-house-card><a href="/house/{listing_id}"><h2 class="caseName">測試住宅</h2><span class="address">{address}</span><span class="price">1500</span><span class="room">2房</span></a></yc-ng-buy-house-card>'


class Client:
    def __init__(self, handler):
        self.handler = handler
        self.blocked = set()
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        result = self.handler(url)
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(text=result, url=url, status_code=200)


def test_all_regions_and_linked_pages(monkeypatch):
    def html(url):
        region = source.REGIONS.index(next(r for r in source.REGIONS if source.quote(r, safe='/-') in url))
        page = 2 if 'pg=2' in url else 1
        return card(str(region * 10 + page)) + '<p>共2筆</p><a href="?pg=1">1</a><a href="?pg=2">2</a>'
    client = Client(html)
    frames, reports = source.collect('fixture', client)
    assert len(frames) == 10 and len(client.urls) == 10
    assert {r['region'] for r in reports} == set(source.REGIONS)
    assert all(r['complete'] and r['listing_coverage'] == 1 for r in reports)
    assert all(r['pages_succeeded'] == 2 for r in reports)
    assert any('二重埔' in a for f in frames for a in f.address)


def test_page_failure_preserves_success_and_continues_regions(monkeypatch):
    monkeypatch.setattr(source, 'REGIONS', ['新竹市-', '新竹縣-竹北市'])
    def html(url):
        if 'pg=2' in url:
            return requests.Timeout('fixture timeout')
        first = source.quote('新竹市-', safe='/-') in url
        return card('1' if first else '2') + ('<a href="?pg=2">2</a><p>共2筆</p>' if first else '<p>共1筆</p>')
    frames, reports = source.collect('fixture', Client(html))
    assert {x for f in frames for x in f.listing_id} == {'1', '2'}
    assert reports[0]['status'] == 'partial' and reports[0]['pages_succeeded'] == 1
    assert reports[0]['listing_coverage'] == .5
    assert reports[1]['complete']


def test_unknown_pagination_is_not_full_coverage(monkeypatch):
    monkeypatch.setattr(source, 'REGIONS', ['新竹市-'])
    _, reports = source.collect('fixture', Client(lambda _: card('1')))
    assert reports[0]['status'] == 'partial'
    assert reports[0]['listing_coverage'] is None


def test_repeated_page_is_detected_and_empty_scan_is_explicit(monkeypatch):
    monkeypatch.setattr(source, 'REGIONS', ['新竹市-'])
    _, reports = source.collect('fixture', Client(lambda _: card('1') + '<a href="?pg=2">2</a><p>共2筆</p>'))
    assert not reports[0]['complete'] and reports[0]['errors']
    frames, reports = source.collect('fixture', Client(lambda _: '<p>共0筆</p>'))
    assert not frames and reports[0]['complete']


def test_page_links_cannot_change_filters_or_hosts():
    root = source.BASE + 'list/query'
    html = '<a href="?pg=2">2</a><a href="?pg=3&amp;price=0">bad</a><a href="https://example.com/list/query?pg=4">bad</a>'
    links, _, _ = source.page_links(html, root, root)
    assert links == [root + '?pg=2']


def listing(i, timestamp='2026-01-01', price=1500):
    return dict(listing_id=str(i), source='永慶公開HTML', url=source.BASE + 'house/' + str(i),
                collected_at=timestamp, title='測試住宅', name='測試住宅', address='新竹市東區測試路',
                price=price, area=30, rooms=2, floor='3/10樓')


def test_partial_adapters_publish_and_retain_history(tmp_path, monkeypatch):
    monkeypatch.setattr(collector, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(collector, 'OUTPUT', tmp_path / 'houses.csv')
    monkeypatch.setattr(database, 'DB_PATH', str(tmp_path / 'houses.db'))
    pd.DataFrame([listing('1')]).to_csv(collector.OUTPUT, index=False)
    import_csv(collector.OUTPUT)
    def failed(*args, **kwargs):
        raise requests.Timeout('adapter unavailable')
    def success(*args, **kwargs):
        return [pd.DataFrame([listing('2', '2026-01-02')])], [dict(status='success', complete=True)]
    monkeypatch.setattr(collector, 'verify_listings', lambda df, t, **kw: dict(checked_at=t, rows=[], verified_available=0))
    result = collector.collect_all([failed, success], Client(lambda _: ''))
    assert set(result.listing_id) == {'1', '2'}
    report = json.loads((tmp_path / 'collection_report.json').read_text())
    assert report['status'] == 'partial' and report['published'] and report['retained_count'] == 1
    import_csv(collector.OUTPUT)
    with database.connect() as con:
        old = con.execute("SELECT last_seen, last_status, active FROM houses WHERE listing_id='1'").fetchone()
        assert tuple(old) == ('2026-01-01', 'new', 1)
        assert con.execute('SELECT COUNT(*) FROM price_history').fetchone()[0] == 2
    original = collector.OUTPUT.read_bytes()
    with pytest.raises(RuntimeError):
        collector.collect_all([failed], Client(lambda _: ''))
    assert collector.OUTPUT.read_bytes() == original
    assert json.loads((tmp_path / 'last_collection_attempt.json').read_text())['status'] == 'failed'


def detail(row, extra='預約看屋'):
    return f'<link rel="canonical" href="{row["url"]}"><h1>{row["title"]}</h1><main>1500萬 30坪 3/10樓 {extra}</main>'


@pytest.mark.parametrize('change,expected', [
    ('ok', 'verified_available'), ('sold', 'explicitly_offmarket'),
    ('noaction', 'unverified_availability'), ('wrongtitle', 'unverified_identity'),
    ('changedprice', 'unverified_changed_details'), ('changedarea', 'unverified_changed_details'),
    ('changedfloor', 'unverified_changed_details'), ('nocanonical', 'unverified_identity')])
def test_detail_requires_identity_details_and_availability(change, expected):
    row = listing('1')
    html = detail(row)
    if change == 'sold': html = detail(row, '本物件已成交')
    if change == 'noaction': html = detail(row, '')
    if change == 'wrongtitle': html = html.replace('<h1>測試住宅</h1>', '<h1>別的住宅</h1>')
    if change == 'changedprice': html = html.replace('1500萬', '1600萬')
    if change == 'changedarea': html = html.replace('30坪', '31坪')
    if change == 'changedfloor': html = html.replace('3/10樓', '4/10樓')
    if change == 'nocanonical': html = '<h1>測試住宅</h1>1500萬 30坪 3/10樓 預約看屋'
    assert classify_detail(html, row['url'], row) == expected
    assert classify_detail(detail(row), source.BASE + 'list/', row) == 'unverified_redirect'


def test_detail_failure_does_not_prevent_next_listing():
    response = requests.Response(); response.status_code = 404
    error = requests.HTTPError('not found', response=response)
    client = Client(lambda url: error if url.endswith('/1') else detail(listing('2')))
    result = verify_listings(pd.DataFrame([listing('1'), listing('2')]), 'fixture', client)
    assert [c['status'] for c in result['rows']] == ['unavailable_http', 'verified_available']
    assert len(client.urls) == 2


def test_checks_are_bound_to_current_attempt_and_expire(tmp_path):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    timestamp = now.isoformat()
    row = listing('1')
    check = dict(row, status='verified_available', checked_at=timestamp)
    path, attempt = tmp_path / 'checks.json', tmp_path / 'attempt.json'
    path.write_text(json.dumps(dict(checked_at=timestamp, rows=[check])))
    attempt.write_text(json.dumps(dict(collected_at=timestamp)))
    checks = load_checks(path, attempt, now)
    assert row_check(row, checks)['status'] == 'verified_available'
    assert row_check(dict(row, address='changed'), checks)['status'] == 'not_verified_this_run'
    assert load_checks(path, attempt, now + timedelta(hours=25)) == {}
    attempt.write_text(json.dumps(dict(collected_at='newer failed run')))
    assert load_checks(path, attempt, now) == {}


def route_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, 'ROOT', tmp_path)
    monkeypatch.setattr(routes.time, 'sleep', lambda _: None)
    data = tmp_path / 'data'; data.mkdir()
    destinations = [dict(id='work1', lat=24.7, lon=121.0), dict(id='work2', lat=24.8, lon=121.1)]
    (data / 'destinations.json').write_text(json.dumps(dict(destinations=destinations)))
    pin = dict(lat=24.75, lon=121.05, status='reviewed_exact_door_pin')
    (data / 'transaction_pins.json').write_text(json.dumps({'測試路1號': pin}))
    proxy = dict(listing_id='1', listing_address='測試路', listing_collected_at='fixture',
                 doors=[dict(proxy_address='測試路1號')])
    (data / 'transaction_proxies.json').write_text(json.dumps(dict(rows=[proxy])))
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: dict(code='Ok', routes=[dict(distance=7000)], waypoints=[dict(distance=0), dict(distance=1)]))
    monkeypatch.setattr(routes.requests, 'get', get)
    return data, destinations, pin, proxy, calls


def test_permanent_cache_survives_no_current_listing_and_relisting(tmp_path, monkeypatch):
    data, destinations, pin, proxy, calls = route_fixture(tmp_path, monkeypatch)
    routes.calculate()
    assert len(calls) == 2
    result = json.loads((data / 'commute_estimates.json').read_text())
    assert result['rows'][0]['total_max_km'] == 14  # synthetic fixture, not real road data
    routes.calculate()
    assert len(calls) == 2
    (data / 'transaction_proxies.json').write_text(json.dumps(dict(rows=[])))
    routes.calculate()
    assert len(json.loads((data / 'route_cache.json').read_text())['entries']) == 1
    proxy['listing_collected_at'] = 'later'
    (data / 'transaction_proxies.json').write_text(json.dumps(dict(rows=[proxy])))
    routes.calculate()
    assert len(calls) == 2
    pin['lat'] += .001
    (data / 'transaction_pins.json').write_text(json.dumps({'測試路1號': pin}))
    routes.calculate()
    assert len(calls) == 4
    destinations[0]['lat'] += .001
    (data / 'destinations.json').write_text(json.dumps(dict(destinations=destinations)))
    routes.calculate()
    assert len(calls) == 6
    assert routes.route_key('測試路1號', pin, destinations) != routes.route_key('測試路2號', pin, destinations)


def test_failed_route_retries_without_poisoning_cache(tmp_path, monkeypatch):
    data, destinations, pin, proxy, calls = route_fixture(tmp_path, monkeypatch)
    good_get = routes.requests.get
    def bad_get(*args, **kwargs):
        raise requests.Timeout('fixture')
    monkeypatch.setattr(routes.requests, 'get', bad_get)
    routes.calculate()
    assert json.loads((data / 'route_cache.json').read_text())['entries'] == {}
    monkeypatch.setattr(routes.requests, 'get', good_get)
    routes.calculate()
    assert len(calls) == 2
    cached = json.loads((data / 'route_cache.json').read_text())['entries']
    value = next(iter(cached.values()))
    assert routes.valid_cached_route(value)
    value['distances_km'][0] = float('nan')
    assert not routes.valid_cached_route(value)
