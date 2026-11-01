"""Traverse public pagination without bypassing access restrictions."""
import re
import time
from urllib.parse import quote, urljoin, urlsplit, urlunsplit, parse_qsl, urlencode
from urllib.robotparser import RobotFileParser

import pandas as pd
import requests
from bs4 import BeautifulSoup

BASE = "https://buy.yungching.com.tw/"
REGIONS = ["新竹市-", "新竹縣-竹北市", "新竹縣-竹東鎮", "新竹縣-寶山鄉", "新竹縣-芎林鄉"]
UA = "HsinchuHouseTracker/0.1 (+https://github.com/allenhong1113-png/hsinchu-house-tracker)"


def parse_html(html, page_url, timestamp):
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("yc-ng-buy-house-card")
    if not cards:
        raise ValueError("No public listing cards: blocked, empty, or changed markup; not a successful scan")
    rows = []
    for card in cards:
        def text(selector):
            element = card.select_one(selector)
            return element.get_text(" ", strip=True) if element else ""
        def number(value):
            match = re.search(r"[0-9]+(?:\.[0-9]+)?", value.replace(",", ""))
            return float(match.group()) if match else None
        link = card.select_one('a[href]')
        if not link or not re.fullmatch(r"/?house/[0-9]+", link["href"]):
            continue
        url = urljoin(BASE, link["href"])
        address = text(".address")
        district = "新竹市" if address.startswith("新竹市") else next((d for d in ["竹北市", "竹東鎮", "寶山鄉", "芎林鄉"] if d in address), "")
        info = text(".case-info")
        age_match = re.search(r"([0-9]+(?:\.[0-9]+)?)年", info)
        title = text(".caseName")
        note = text(".note")
        # Reject obvious 1+1 / 2+1 / converted bedrooms even when the site's room field says 2.
        altered = bool(re.search(r"[123一二三]\s*[+＋]\s*[1一]|[三3]\s*改\s*[二2]|[一1]\s*改\s*[二2]|雙套|樓中樓", title + note))
        rows.append(dict(listing_id=url.rsplit("/", 1)[-1], name=text(".community") or title,
                         title=title, district=district, address=address, price=number(text(".price")),
                         area=number(text(".regArea")), age=float(age_match.group(1)) if age_match else None,
                         rooms=number(text(".room")), parking=text(".car").removesuffix("車位"),
                         floor=text(".floor"), source="永慶公開HTML", url=url, collected_at=timestamp,
                         layout_status="excluded_conversion" if altered else "advertised_2_rooms",
                         source_page=page_url, geocode_status="unverified", route_status="unverified"))
    if not rows:
        raise ValueError("Listing cards found but no valid public listing URLs")
    return pd.DataFrame(rows)



class AccessBlocked(ValueError):
    pass


class PublicClient:
    """One paced session for search and detail checks; never retry a blocked host."""
    def __init__(self):
        self.session = requests.Session()
        self.session.headers['User-Agent'] = UA
        self.robots = {}
        self.blocked = set()
        self.last = 0

    def get(self, url):
        host = urlsplit(url).netloc
        if urlsplit(url).scheme != 'https' or host != urlsplit(BASE).netloc:
            raise ValueError('Unsupported source URL')
        if host in self.blocked:
            raise AccessBlocked('Source access already failed; no alternate endpoint attempt')
        if host not in self.robots:
            robots_url = urljoin(BASE, 'robots.txt')
            try:
                response = self.session.get(robots_url, timeout=30)
                response.raise_for_status()
                if response.url != robots_url:
                    raise AccessBlocked('Unexpected robots redirect')
                robot = RobotFileParser(robots_url)
                robot.parse(response.text.lstrip('\ufeff').splitlines())
                self.robots[host] = robot
            except (requests.RequestException, ValueError):
                self.blocked.add(host)
                raise
        robot = self.robots[host]
        if not robot.can_fetch(UA, url):
            raise AccessBlocked('robots.txt disallows this URL')
        delay = max(3, robot.crawl_delay(UA) or 0)
        time.sleep(max(0, delay - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        response = self.session.get(url, timeout=45)
        if response.status_code in (401, 403, 429):
            self.blocked.add(host)
            raise AccessBlocked('Source access restriction HTTP ' + str(response.status_code))
        response.raise_for_status()
        if urlsplit(response.url).netloc != host:
            raise ValueError('Unexpected off-site redirect')
        text = BeautifulSoup(response.text, 'html.parser').get_text(' ', strip=True)
        if re.search(r'verify you are human|checking your browser|captcha|access denied', text, re.I):
            self.blocked.add(host)
            raise AccessBlocked('Public source returned an access challenge')
        return response


def page_links(html, page_url, root_url):
    """Follow only rendered links for this exact query, never invent a page URL."""
    soup = BeautifulSoup(html, 'html.parser')
    root = urlsplit(root_url)
    fixed = {k: v for k, v in parse_qsl(root.query) if k not in ('pg', 'page')}
    links = []
    for a in soup.select('a[href]'):
        target = urlsplit(urljoin(page_url, a['href']))
        query = dict(parse_qsl(target.query))
        if (target.scheme != root.scheme or target.netloc != root.netloc
                or target.path.rstrip('/') != root.path.rstrip('/')
                or {k: v for k, v in query.items() if k not in ('pg', 'page')} != fixed):
            continue
        if not any(query.get(k, '').isdigit() for k in ('pg', 'page')):
            continue
        # The first page often links back to ?pg=1; do not re-read it as a new page.
        if any(query.get(k) == '1' for k in ('pg', 'page')):
            query.pop('pg', None)
            query.pop('page', None)
        clean = urlunsplit((target.scheme, target.netloc, target.path, urlencode(sorted(query.items())), ''))
        if clean not in links:
            links.append(clean)
    text = soup.get_text(' ', strip=True)
    total = re.search(r'共\s*([\d,]+)\s*筆', text)
    total = int(total[1].replace(',', '')) if total else None
    terminal = any(re.search(r'下一頁|next', a.get_text(' ', strip=True) + ' ' + str(a.get('aria-label', '')), re.I)
                   for a in soup.select('[aria-disabled="true"], .disabled'))
    empty = total == 0 and not soup.select('yc-ng-buy-house-card')
    return links, total, terminal or empty


def collect(timestamp, client=None):
    client = client or PublicClient()
    datasets, reports = [], []
    for region in REGIONS:
        root = BASE + 'list/' + quote(region + '_c/1000-2000_price/2-2_rmp', safe='/-')
        queue, visited, successful, errors, identities = [root], set(), [], [], set()
        terminal = False
        total = None
        while queue:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            try:
                response = client.get(url)
                if urlsplit(response.url).path.rstrip('/') != urlsplit(root).path.rstrip('/'):
                    raise ValueError('Unexpected search redirect')
                links, found_total, found_terminal = page_links(response.text, response.url, root)
                if found_total is not None:
                    total = max(total or 0, found_total)
                terminal = terminal or found_terminal
                if found_total == 0:
                    df = pd.DataFrame()
                else:
                    df = parse_html(response.text, response.url, timestamp)
                    ids = set(df.listing_id.astype(str))
                    if identities and ids.issubset(identities):
                        raise ValueError('Repeated page results; pagination was not honoured')
                    identities.update(ids)
                    datasets.append(df)
                successful.append(url)
                queue.extend(link for link in links if link not in visited and link not in queue)
            except (requests.RequestException, ValueError) as exc:
                errors.append(dict(url=url, error=str(exc)))
                if isinstance(exc, AccessBlocked) or client.blocked:
                    # A source-level block is not a reason to probe other regions.
                    break
        discovered = visited | set(queue)
        exhausted = not queue and not errors
        complete = exhausted and (terminal or total is not None) and (total is None or len(identities) >= total)
        reports.append(dict(source='永慶公開HTML', region=region, url=root,
                            status='success' if complete else ('partial' if successful else 'failed'),
                            complete=complete, count=len(identities), total_results=total,
                            pages_attempted=len(visited), pages_succeeded=len(successful),
                            pages_discovered=len(discovered), successful_urls=successful,
                            pending_urls=queue, errors=errors,
                            discovered_page_coverage=len(successful) / len(discovered),
                            listing_coverage=(min(1, len(identities) / total) if total else (1 if complete else None)),
                            coverage_note='Public query coverage only; unknown pagination is incomplete'))
    return datasets, reports
