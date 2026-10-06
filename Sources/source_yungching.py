"""Low-volume PoC: one public search page per region, not a market census."""
import re
import time
from urllib.parse import quote, urljoin
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


def collect(timestamp):
    session = requests.Session()
    session.headers["User-Agent"] = UA
    robots_url = urljoin(BASE, "robots.txt")
    r = session.get(robots_url, timeout=30)
    r.raise_for_status()
    robots = RobotFileParser(robots_url)
    robots.parse(r.text.lstrip("\ufeff").splitlines())
    datasets, reports = [], []
    for region in REGIONS:
        url = BASE + "list/" + quote(region + "_c/1000-2000_price/2-2_rmp", safe="/-")
        if not robots.can_fetch(UA, url):
            reports.append(dict(url=url, status="robots_disallowed", count=0))
            continue
        time.sleep(max(3, robots.crawl_delay(UA) or 0))
        try:
            response = session.get(url, timeout=45)
            response.raise_for_status()
            if not response.url.startswith(BASE + "list/"):
                raise ValueError("Unexpected redirect: no login or alternate-route fallback")
            df = parse_html(response.text, response.url, timestamp)
            datasets.append(df)
            reports.append(dict(url=response.url, status="success", count=len(df)))
        except (requests.RequestException, ValueError) as exc:
            reports.append(dict(url=url, status="failed", count=0, error=str(exc)))
            # No retries or alternative endpoints after access failure.
            break
    return datasets, reports
