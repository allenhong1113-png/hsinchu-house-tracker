"""Detail-page checks are independent of search absence and distance eligibility."""
import json
import math
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlsplit
import pandas as pd
import requests
from bs4 import BeautifulSoup
from Sources.source_yungching import PublicClient, AccessBlocked, BASE


def identity(row):
    return str(row['source']) + '|' + str(row['listing_id'])


def classify_detail(html, final_url, row):
    expected = '/house/' + str(row['listing_id'])
    if urlsplit(final_url).netloc != urlsplit(BASE).netloc or urlsplit(final_url).path.rstrip('/') != expected:
        return 'unverified_redirect'
    soup = BeautifulSoup(html, 'html.parser')
    canonical = soup.select_one('link[rel="canonical"][href]')
    if not canonical or urlsplit(urljoin(final_url, canonical['href'])).path.rstrip('/') != expected:
        return 'unverified_identity'
    # Recommendations must not supply the identity, price or active status.
    for node in soup.select('yc-ng-buy-house-card, script, .recommend, .recommendations'):
        node.decompose()
    heading = soup.find('h1')
    compact = lambda x: re.sub(r'\s+', '', str(x))
    title = compact(row.get('title') or row.get('name') or '')
    if not heading or not title or title not in compact(heading.get_text(' ', strip=True)):
        return 'unverified_identity'
    text = soup.get_text(' ', strip=True)
    if re.search(r'本物件已(?:下架|成交|售出)|物件已(?:下架|成交|售出)|此物件已(?:下架|成交|售出)', text):
        return 'explicitly_offmarket'
    if not re.search(r'預約看屋|預約賞屋|我要看屋|預約專人帶看|聯絡經紀人', text):
        return 'unverified_availability'
    numbers = [float(x.replace(',', '')) for x in re.findall(r'\d[\d,]*(?:\.\d+)?', text)]
    for field in ('price', 'area'):
        value = row.get(field)
        if value is not None and not pd.isna(value) and not any(math.isclose(float(value), n, abs_tol=.01) for n in numbers):
            return 'unverified_changed_details'
    floor = row.get('floor')
    if isinstance(floor, str) and floor and compact(floor) not in compact(text):
        return 'unverified_changed_details'
    return 'verified_available'


def verify_listings(df, timestamp, client=None):
    client = client or PublicClient()
    checks = []
    for row in df.to_dict('records'):
        check = {k: row.get(k) for k in ('listing_id', 'source', 'url', 'address', 'collected_at')}
        check.update(checked_at=timestamp, status='unverified')
        try:
            response = client.get(row['url'])
            check.update(status=classify_detail(response.text, response.url, row), final_url=response.url,
                         http_status=response.status_code)
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else None
            check.update(status='unavailable_http' if code in (404, 410) else 'unverified_error', http_status=code)
        except (requests.RequestException, ValueError) as exc:
            check.update(status='skipped_access' if isinstance(exc, AccessBlocked) else 'unverified_error', error=str(exc))
        checks.append(check)
    return dict(checked_at=timestamp, rows=checks,
                verified_available=sum(c['status'] == 'verified_available' for c in checks))


def load_checks(path, attempt_path, now=None):
    """A prior run's positive check cannot masquerade as a current verification."""
    if not Path(path).exists() or not Path(attempt_path).exists():
        return {}
    report = json.loads(Path(path).read_text())
    attempt = json.loads(Path(attempt_path).read_text())
    if report.get('checked_at') != attempt.get('collected_at'):
        return {}
    try:
        checked = datetime.fromisoformat(report['checked_at'])
        age = (now or datetime.now(timezone.utc)) - checked
    except (ValueError, TypeError, KeyError):
        return {}
    if age < timedelta(0) or age > timedelta(hours=24):
        return {}
    return {identity(c): c for c in report['rows']}


def row_check(row, checks):
    check = checks.get(identity(row))
    if check and all(str(check.get(k)) == str(row.get(k)) for k in ('url', 'address', 'collected_at')):
        return check
    return {'status': 'not_verified_this_run', 'checked_at': None}
