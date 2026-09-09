#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HA add-on entrypoint: číta /data/options.json, denne spúšťa inkrementálny import z OKTE IMS."""
import json, os, time, subprocess, datetime
from zoneinfo import ZoneInfo

OPTS = "/data/options.json"
TZ = ZoneInfo("Europe/Bratislava")

def opt(k, d=None):
    try:
        return json.load(open(OPTS, encoding="utf-8")).get(k, d)
    except Exception:
        return d

def main():
    os.environ["OKTE_ADDON"] = "1"          # nikdy nechodíme na dev SMB cestu
    os.environ["OKTE_USERNAME"] = str(opt("okte_username", ""))
    os.environ["OKTE_PASSWORD"] = str(opt("okte_password", ""))
    os.environ["OKTE_EIC"] = str(opt("eic", ""))
    os.environ["OKTE_STAT_ID"] = str(opt("statistic_id", "okte:elektrina_spotreba"))
    os.environ["OKTE_STAT_NAME"] = str(opt("statistic_name", "OKTE IMS – spotreba zo siete"))
    ha_token_opt = str(opt("ha_token", "")).strip()
    sup = os.environ.get("SUPERVISOR_TOKEN") or os.environ.get("HASSIO_TOKEN") or ""
    os.environ["HA_TOKEN"] = ha_token_opt or sup
    ha_ws = str(opt("ha_ws_url", "")).strip()
    if ha_token_opt:
        # s vlastným long-lived tokenom ideme PRIAMO na core (HTTPS/self-signed -> wss + verify off)
        if not ha_ws or "supervisor/core" in ha_ws or ha_ws.startswith("ws://homeassistant"):
            ha_ws = "wss://homeassistant:8123/api/websocket"
    elif not ha_ws:
        ha_ws = "ws://supervisor/core/websocket"
    os.environ["HA_WS_URL"] = ha_ws
    os.environ["OKTE_ALARM"] = "1" if bool(opt("alarm_enabled", True)) else "0"
    os.environ["OKTE_ALARM_MULT"] = str(opt("alarm_multiplier", 2.0))
    os.environ["OKTE_ALARM_MIN"] = str(opt("alarm_min_kwh", 3.0))
    os.environ["OKTE_NOTIFY"] = str(opt("notify_service", "notify.pushover"))
    days = int(opt("backfill_days", 14))
    run_hour = int(opt("run_hour", 6))

    print("[okte_ims] token_len=%d WS=%s | alarm=%s (%s×, min %s kWh) -> %s" % (
        len(os.environ["HA_TOKEN"]), ha_ws, os.environ["OKTE_ALARM"],
        os.environ["OKTE_ALARM_MULT"], os.environ["OKTE_ALARM_MIN"], os.environ["OKTE_NOTIFY"]), flush=True)
    if not os.environ["OKTE_USERNAME"] or not os.environ["OKTE_PASSWORD"]:
        print("[okte_ims] CHYBA: vyplň okte_username a okte_password v Nastaveniach add-onu.", flush=True)

    print("[okte_ims] štart. Denne o %02d:00 (Europe/Bratislava), posledných %d dní, EIC %s -> %s"
          % (run_hour, days, os.environ["OKTE_EIC"], os.environ["OKTE_STAT_ID"]), flush=True)

    while True:
        print("[okte_ims] beh %s" % datetime.datetime.now(TZ).isoformat(timespec="seconds"), flush=True)
        try:
            subprocess.run(["python3", "/app/okte_auto.py", "--days", str(days), "--out", "/data/downloads"],
                           check=False, env=os.environ.copy())
        except Exception as e:
            print("[okte_ims] chyba behu:", e, flush=True)
        now = datetime.datetime.now(TZ)
        nxt = now.replace(hour=run_hour, minute=0, second=0, microsecond=0)
        if nxt <= now:
            nxt += datetime.timedelta(days=1)
        secs = (nxt - now).total_seconds()
        print("[okte_ims] ďalší beh %s (o %.1f h)" % (nxt.isoformat(timespec="minutes"), secs / 3600.0), flush=True)
        time.sleep(max(60, secs))

if __name__ == "__main__":
    main()
