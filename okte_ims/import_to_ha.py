# -*- coding: utf-8 -*-
"""
Import OKTE IMS 15-min exportu do Home Assistant ako long-term statistics.
  15-min kW -> hodinové kWh -> kumulatívny súčet -> WS recorder/import_statistics.
Externá štatistika (kWh, has_sum) -> pridateľná do Energy dashboardu.

Použitie:
  python import_to_ha.py <zip_alebo_priecinok> [--eic <EIC>] [--dry-run]
"""
import sys, os, io, json, ssl, glob, argparse, datetime
from zoneinfo import ZoneInfo
import parse_ims

TZ = ZoneInfo("Europe/Bratislava")
# HA cieľ + token z env (v add-one ich nastaví run.py z options).
HA_WS = os.getenv("HA_WS_URL", "ws://homeassistant:8123/api/websocket")
STAT_ID = os.getenv("OKTE_STAT_ID", "okte:elektrina_spotreba")
STAT_NAME = os.getenv("OKTE_STAT_NAME", "OKTE IMS – spotreba zo siete")
DEFAULT_EIC = os.getenv("OKTE_EIC", "")

def _ssl_arg():
    if HA_WS.startswith("wss://"):
        ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return None

def get_token():
    t = os.getenv("HA_TOKEN")            # add-on: ha_token option (long-lived token)
    if not t:
        raise SystemExit("Chýba HA token — nastav env HA_TOKEN alebo add-on option 'ha_token'.")
    return t

def collect_hourly(paths, eic):
    """Vráti zoradený zoznam (hour_dt_local, kwh_hodina) pre dané EIC."""
    hourly = {}
    files = []
    for p in paths:
        if os.path.isdir(p):
            files += glob.glob(os.path.join(p, "*.zip")) + glob.glob(os.path.join(p, "*.csv"))
        else:
            files.append(p)
    seen_eics = set()
    intervals = {}   # dt(15-min) -> kwh ; DEDUPE naprieč súbormi (rovnaký interval = rovnaká hodnota => prepísať)
    for f in files:
        kind, res = parse_ims.parse(f)
        if kind != "interval15":
            print("  (preskakujem %s — typ %s, nie 15-min)" % (os.path.basename(f), kind))
            continue
        for e, rows in res.items():
            seen_eics.add(e)
            if e != eic:
                continue
            for x in rows:
                if x["kwh"] is None:
                    continue
                intervals[x["dt"]] = x["kwh"]
    # až teraz agregácia na hodiny (4×15-min sčítať, ale každý interval len raz)
    for dt, kwh in intervals.items():
        h = dt.replace(minute=0, second=0, microsecond=0)
        hourly[h] = hourly.get(h, 0.0) + kwh
    if eic not in seen_eics:
        print("!! POZOR: EIC %s sa v dátach nenašiel. Nájdené EIC: %s" % (eic, ", ".join(sorted(seen_eics)) or "žiadne"))
    return sorted(hourly.items())

def build_stats(hourly, base_sum=0.0):
    stats = []
    running = float(base_sum)
    for h, kwh in hourly:
        running += kwh
        start_local = datetime.datetime(h.year, h.month, h.day, h.hour, tzinfo=TZ)
        stats.append({"start": start_local.isoformat(), "state": round(running, 3), "sum": round(running, 3)})
    return stats

async def get_last_sum(before_dt):
    """Posledný kumulatívny sum štatistiky STAT_ID pred časom before_dt (tz-aware). 0.0 ak nič."""
    import websockets
    tok = get_token()
    async with websockets.connect(HA_WS, ssl=_ssl_arg(), max_size=None) as ws:
        json.loads(await ws.recv()); await ws.send(json.dumps({"type": "auth", "access_token": tok}))
        if json.loads(await ws.recv()).get("type") != "auth_ok":
            raise SystemExit("WS auth zlyhala (get_last_sum)")
        start = (before_dt - datetime.timedelta(days=4)).isoformat()
        await ws.send(json.dumps({"id": 1, "type": "recorder/statistics_during_period",
            "start_time": start, "end_time": before_dt.isoformat(),
            "statistic_ids": [STAT_ID], "period": "hour"}))
        rows = json.loads(await ws.recv())["result"].get(STAT_ID, [])
        bms = before_dt.timestamp() * 1000
        prev = [r for r in rows if r["start"] < bms and r.get("sum") is not None]
        return prev[-1]["sum"] if prev else 0.0

def call_notify(service, title, message):
    """Zavolá HA notify službu (napr. notify.pushover) cez REST."""
    import urllib.request
    dom, name = service.split(".", 1)
    base = HA_WS.replace("wss://", "https://").replace("ws://", "http://").split("/api/")[0]
    url = "%s/api/services/%s/%s" % (base, dom, name)
    data = json.dumps({"title": title, "message": message}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
        headers={"Authorization": "Bearer " + get_token(), "Content-Type": "application/json"})
    kw = {"timeout": 20}
    if base.startswith("https://"):
        c = ssl.create_default_context(); c.check_hostname = False; c.verify_mode = ssl.CERT_NONE
        kw["context"] = c
    urllib.request.urlopen(req, **kw).read()

def set_ha_sensor(entity_id, state, attributes):
    """Nastaví stav senzora v HA cez REST (pre zrkadlenie na druhú HA cez remote_homeassistant)."""
    import urllib.request
    base = HA_WS.replace("wss://", "https://").replace("ws://", "http://").split("/api/")[0]
    url = "%s/api/states/%s" % (base, entity_id)
    body = json.dumps({"state": state, "attributes": attributes}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
        headers={"Authorization": "Bearer " + get_token(), "Content-Type": "application/json"})
    kw = {"timeout": 20}
    if base.startswith("https://"):
        c = ssl.create_default_context(); c.check_hostname = False; c.verify_mode = ssl.CERT_NONE
        kw["context"] = c
    urllib.request.urlopen(req, **kw).read()

def mirror_attrs():
    """Atribúty zrkadleného senzora (rovnaké pri dennom behu aj pri obnove po reštarte HA)."""
    return {"unit_of_measurement": "kWh", "device_class": "energy",
            "state_class": "total_increasing",
            "friendly_name": os.getenv("OKTE_STAT_NAME", "OKTE IMS spotreba")}

def get_ha_state(entity_id):
    """Stav entity cez REST; None ak entita v HA neexistuje (404)."""
    import urllib.request, urllib.error
    base = HA_WS.replace("wss://", "https://").replace("ws://", "http://").split("/api/")[0]
    req = urllib.request.Request("%s/api/states/%s" % (base, entity_id),
        headers={"Authorization": "Bearer " + get_token()})
    kw = {"timeout": 20}
    if base.startswith("https://"):
        c = ssl.create_default_context(); c.check_hostname = False; c.verify_mode = ssl.CERT_NONE
        kw["context"] = c
    try:
        return json.loads(urllib.request.urlopen(req, **kw).read()).get("state")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise

async def send_to_ha(stats):
    import websockets
    meta = {"has_mean": False, "has_sum": True, "name": STAT_NAME,
            "source": STAT_ID.split(":")[0], "statistic_id": STAT_ID, "unit_of_measurement": "kWh"}
    tok = get_token()
    async with websockets.connect(HA_WS, ssl=_ssl_arg(), max_size=None) as ws:
        json.loads(await ws.recv())  # auth_required
        await ws.send(json.dumps({"type": "auth", "access_token": tok}))
        auth = json.loads(await ws.recv())
        if auth.get("type") != "auth_ok":
            raise SystemExit("WS auth zlyhala: %s" % auth)
        await ws.send(json.dumps({"id": 1, "type": "recorder/import_statistics", "metadata": meta, "stats": stats}))
        resp = json.loads(await ws.recv())
        return resp

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="+")
    ap.add_argument("--eic", default=DEFAULT_EIC)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    hourly = collect_hourly(a.path, a.eic)
    if not hourly:
        raise SystemExit("Žiadne hodinové dáta — koniec.")
    stats = build_stats(hourly)
    total = stats[-1]["sum"]
    print("EIC:", a.eic, "| statistic_id:", STAT_ID)
    print("hodín:", len(stats), "| od", stats[0]["start"], "do", stats[-1]["start"])
    print("spolu spotreba:", round(total, 3), "kWh")
    # denný prehľad
    byday = {}
    for (h, kwh) in hourly:
        byday[h.date()] = byday.get(h.date(), 0.0) + kwh
    for d in sorted(byday):
        print("   %s : %.3f kWh" % (d, byday[d]))
    print("ukážka prvých 3 hodín:", stats[:3])

    if a.dry_run:
        print("\n[DRY-RUN] nič sa neposlalo do HA.")
        return
    import asyncio
    resp = asyncio.run(send_to_ha(stats))
    print("\nHA odpoveď:", resp)
    if resp.get("success"):
        print("OK — štatistika %s naimportovaná (%d hodín)." % (STAT_ID, len(stats)))
    else:
        print("!! Import zlyhal.")

if __name__ == "__main__":
    main()
