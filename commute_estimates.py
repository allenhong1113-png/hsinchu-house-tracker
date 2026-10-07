"""Public transaction-door proxies; never change the listing's exact address/coordinates.
No automatic geocoder: reviewed exact-door pins are supplied in data/transaction_pins.json.
"""
import argparse
import hashlib
import json
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
import pandas as pd
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
UA = 'hsinchu-house-tracker/0.2 public-data PoC (github.com/allenhong1113-png/hsinchu-house-tracker)'

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def destination_digest():
    d = json.loads((ROOT/'data/destinations.json').read_text())['destinations']
    return digest([{k:x[k] for k in ('id','lat','lon')} for x in d])

def parse_transactions(html, listing_address):
    """Only public rendered ministry records, on the listing's own street."""
    soup = BeautifulSoup(html, 'html.parser')
    out = []
    street = re.sub(r'^新竹(?:市|縣)(?:東區|北區|香山區|竹北市|竹東鎮|寶山鄉|芎林鄉)', '', listing_address)
    for card in soup.select('article.deal-card'):
        node = card.select_one('.deal-card__address')
        if not node or '來源：內政部實價登錄' not in card.get_text('', strip=True):
            continue
        raw = node.get_text('', strip=True)
        normalized = raw.replace('新竹市新竹市', '新竹市').replace('新竹縣新竹縣','新竹縣')
        # Remove floor only; retain lanes, alleys and sub-number doors.
        m = re.search(r'^(.*?\d+(?:之\d+)?號)', normalized)
        if not m or street not in m[1] or not re.match(r'^新竹[市縣]',m[1]):
            continue
        door = m[1]
        if door.startswith('新竹市') and not re.match(r'^新竹市(?:東區|北區|香山區)',door):
            district = re.match(r'^(新竹市(?:東區|北區|香山區))',listing_address)
            if district: door = district[1] + door[3:]
        date = card.select_one('.deal-card__date')
        out.append(dict(proxy_address=door, transaction_address=raw, transaction_month=date.get_text(strip=True) if date else None))
    return list({x['proxy_address']:x for x in out}.values())

class PublicPages:
    def __init__(self):
        self.session=requests.Session(); self.session.headers['User-Agent']=UA
        self.robots={}; self.last=0
    def get(self,url):
        host=urlparse(url).netloc
        if host not in ('buy.yungching.com.tw','community.yungching.com.tw'):
            raise ValueError('Unexpected public source host')
        if host not in self.robots:
            r=self.session.get('https://'+host+'/robots.txt',timeout=25);r.raise_for_status()
            robot=RobotFileParser();robot.parse(r.text.splitlines());self.robots[host]=robot
        if not self.robots[host].can_fetch(UA,url):raise ValueError('robots.txt disallows '+url)
        time.sleep(max(0,3-(time.monotonic()-self.last)))
        self.last=time.monotonic()
        r=self.session.get(url,timeout=25);r.raise_for_status()
        if re.search(r'verify you are human|captcha|access denied',BeautifulSoup(r.text,'html.parser').get_text(' ',strip=True),re.I):
            raise ValueError('Public source returned access restriction')
        return r.text

def discover(limit=None):
    df=pd.read_csv(ROOT/'data/houses.csv',dtype={'listing_id':str})
    df=df[df.price.between(1000,2000)&(df.rooms==2)&(df.age<=20)&(df.parking=='坡道平面')&(df.layout_status=='advertised_2_rooms')]
    df=df[~(df['name'].fillna('')+df.title.fillna('')).str.replace(' ','',regex=False).str.contains('綠光森林16',regex=False)]
    candidate_count=len(df)
    if limit: df=df.head(limit)
    pages=PublicPages();cache={};rows=[];errors=[]
    try:
        for _,h in df.iterrows():
            html=pages.get(h.url)
            soup=BeautifulSoup(html,'html.parser')
            links={urljoin(h.url,a['href']) for a in soup.select('.address a.community[href]') if re.fullmatch(r'https://community\.yungching\.com\.tw/building/\d+',urljoin(h.url,a['href']))}
            if len(links)!=1:
                errors.append(dict(listing_id=h.listing_id,reason='No unique explicitly linked community'));continue
            community=links.pop()
            if community not in cache:
                overview=BeautifulSoup(pages.get(community),'html.parser')
                prices=[urljoin('https://community.yungching.com.tw/',a['href']) for a in overview.select('a[href]') if re.fullmatch(r'(?:/)?building/\d+/price',a['href'])]
                if not prices:cache[community]=None
                else:cache[community]=(prices[0],pages.get(prices[0]))
            if cache[community]:
                price_url,price_html=cache[community]
                doors=parse_transactions(price_html,h.address)
                rows.append(dict(listing_id=h.listing_id,listing_url=h.url,listing_address=h.address,listing_collected_at=h.collected_at,community_url=community,transaction_url=price_url,doors=doors))
                print(h.listing_id,community,'doors',len(doors),flush=True)
    except (requests.RequestException,ValueError) as exc:
        errors.append(dict(reason=str(exc),stopped=True))
    report=dict(collected_at=datetime.now(timezone.utc).isoformat(),candidate_count=candidate_count,attempt_limit=len(df),linked_listings=len(rows),rows=rows,errors=errors)
    (ROOT/'data/transaction_proxies.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('SUMMARY',len(rows),'linked;',sum(bool(x['doors']) for x in rows),'with doors; errors',len(errors),flush=True)

def calculate():
    proxies=json.loads((ROOT/'data/transaction_proxies.json').read_text())
    pins=json.loads((ROOT/'data/transaction_pins.json').read_text())
    destinations=json.loads((ROOT/'data/destinations.json').read_text())['destinations']
    endpoint='https://routing.openstreetmap.de/routed-car/route/v1/driving/'
    rows=[];cache={};errors=[]
    for listing in proxies['rows']:
        results=[]
        for door in listing['doors']:
            p=pins.get(door['proxy_address'])
            if not p or p.get('status')!='reviewed_exact_door_pin':continue
            if door['proxy_address'] not in cache:
                distances=[];snap=[]
                try:
                    for d in destinations:
                        time.sleep(1.1)
                        coords=f"{p['lon']},{p['lat']};{d['lon']},{d['lat']}"
                        r=requests.get(endpoint+coords,params={'overview':'false','radiuses':'200;200'},headers={'User-Agent':UA},timeout=30);r.raise_for_status();j=r.json()
                        if j.get('code')!='Ok' or len(j.get('routes',[]))!=1:raise ValueError('No road route')
                        distance=j['routes'][0]['distance']/1000
                        if not math.isfinite(distance) or distance<=0:raise ValueError('Invalid route distance')
                        distances.append(distance);snap.append([w['distance'] for w in j['waypoints']])
                    cache[door['proxy_address']]=dict(**door,**p,distances_km=distances,road_snap_distances_m=snap)
                except (requests.RequestException,ValueError,KeyError) as exc:
                    errors.append(dict(proxy_address=door['proxy_address'],reason=str(exc)));cache[door['proxy_address']]=None
            if cache[door['proxy_address']]:results.append(cache[door['proxy_address']])
        if results:
            rows.append(dict(**{k:v for k,v in listing.items() if k!='doors'},status='estimated_transaction_proxy',door_count=len(listing['doors']),routed_door_count=len(results),complete_doors=len(results)==len(listing['doors']),proxies=results,total_min_km=min(sum(p['distances_km']) for p in results),total_max_km=max(sum(p['distances_km']) for p in results)))
    report=dict(calculated_at=datetime.now(timezone.utc).isoformat(),destination_digest=destination_digest(),route_provider='OSRM / FOSSGIS, car fastest-route distance; © OpenStreetMap contributors (ODbL)',policy_url='https://routing.openstreetmap.de/about.html',rows=rows,errors=errors)
    (ROOT/'data/commute_estimates.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('ROUTED',len(rows),'listings;',len(cache),'doors',flush=True)

def load_estimates(path=None):
    path=path or ROOT/'data/commute_estimates.json'
    if not path.exists():return {}
    report=json.loads(path.read_text())
    if report.get('destination_digest')!=destination_digest():return {}
    return {r['listing_id']:r for r in report['rows'] if r.get('status')=='estimated_transaction_proxy'}

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('mode',choices=['discover','calculate']);a.add_argument('--limit',type=int);args=a.parse_args()
    discover(args.limit) if args.mode=='discover' else calculate()
