"""Read offline, explicitly labelled community-proxy driving observations."""
import json
import math
from pathlib import Path


def destination_key(payload):
    return sorted((d['id'], float(d['lat']), float(d['lon']))
                  for d in payload['destinations'])


def load_known_distances(root=None):
    root = Path(root or Path(__file__).resolve().parent)
    path = root / 'data/known_property_distances.json'
    if not path.exists():
        return {}
    report = json.loads(path.read_text(encoding='utf-8'))
    current = json.loads((root / 'data/destinations.json').read_text(encoding='utf-8'))
    if destination_key(report['destinations']) != destination_key(current):
        return {}
    origins = {r['id']: r for r in report['route_origins']}
    result = {}
    for listing in report['listings']:
        key = str(listing['listing_id'])
        if key in result:
            raise ValueError('Duplicate listing ID in distance report: ' + key)
        origin = origins.get(listing['origin_id'], {})
        legs = origin.get('distances_km', [])
        usable = (origin.get('usable') is True and len(legs) == 2
                  and all(isinstance(k, (int, float)) and not isinstance(k, bool)
                          and math.isfinite(k) and k >= 0 for k in legs)
                  and bool(origin.get('provider')))
        result[key] = dict(listing, origin=origin, usable=usable,
                          total=sum(legs) if usable else None)
    return result


def match_known_distance(row, known):
    entry = known.get(str(row.get('listing_id')))
    if entry and entry.get('address') == row.get('address') and entry.get('url') == row.get('url'):
        return entry
    return None


def report_rows(known):
    rows = []
    for entry in known.values():
        origin = entry['origin']
        usable = entry['usable']
        legs = origin.get('distances_km', [None, None])
        rows.append({'刊登ID': entry['listing_id'], '社區／名稱': entry.get('name'),
                     '行政區': entry.get('district'), '刊登地址': entry.get('address'),
                     'F12P8公里': legs[0] if usable else None,
                     '半吊子廚房公里': legs[1] if usable else None,
                     '合計公里': entry['total'],
                     '距離判定': ('代理位置≤15公里' if entry['total'] <= 15 else '超過15公里') if usable else '定位待確認',
                     '定位依據': origin.get('level'), '實際代理起點': origin.get('used_origin'),
                     '限制': origin.get('note'), '道路來源': origin.get('provider'),
                     '計算時間': origin.get('checked_at'),
                     '售況': '未重新驗證在售', '原始連結': entry.get('url'),
                     '路線連結': ' '.join(origin.get('route_urls', []))})
    return rows
