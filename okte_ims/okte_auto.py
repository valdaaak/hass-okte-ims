# -*- coding: utf-8 -*-
"""
Automatizované sťahovanie IMS priebehových meraní z ims.okte.sk (Ext.NET portál, OIDC login).
Fáza 1: LOGIN + verifikácia session.  (export/download/import doplním po overení loginu)

Secrets v secrets.json {username, password}. Heslo NIKDY nevypisovať.
Test loginu:  python okte_auto.py --login-test
"""
import sys, os, re, json, html
import requests
from urllib.parse import urljoin

HERE = os.path.dirname(os.path.realpath(__file__))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")
APP_ROOT = "https://ims.okte.sk/portal/"
CM_URL = "https://ims.okte.sk/portal/Plugins/IMS/Pages/ContinuousMeasurements/Default.aspx"

def load_secrets():
    u = os.getenv("OKTE_USERNAME"); p = os.getenv("OKTE_PASSWORD")   # add-on options
    if u and p:
        return u, p
    s = json.load(open(os.path.join(HERE, "secrets.json"), encoding="utf-8"))
    if not s.get("password") or s["password"].startswith("SEM_VLOZ"):
        raise SystemExit("!! Chýba OKTE heslo (env OKTE_PASSWORD alebo secrets.json).")
    return s["username"], s["password"]

def form_action(h):
    m = re.search(r'<form\b[^>]*\baction="([^"]*)"', h, re.I)
    return html.unescape(m.group(1)) if m else None

def form_inputs(h):
    """Všetky <input name=..> -> {name: value} (hodnoty un-escapované)."""
    out = {}
    for tag in re.findall(r'<input\b[^>]*>', h, re.I):
        n = re.search(r'\bname="([^"]*)"', tag, re.I)
        v = re.search(r'\bvalue="([^"]*)"', tag, re.I)
        if n:
            out[html.unescape(n.group(1))] = html.unescape(v.group(1)) if v else ""
    return out

def new_session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "sk-SK,sk;q=0.9,en;q=0.8"})
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    # retry len na bezpečné metódy (GET) + connection reset; POST sa NEopakuje (nie duplicitné exporty)
    retry = Retry(total=4, connect=4, read=4, backoff_factor=0.6, status_forcelist=[500, 502, 503, 504])
    ad = HTTPAdapter(max_retries=retry)
    s.mount("https://", ad); s.mount("http://", ad)
    return s

DEBUG = False
def _dbg(tag, r):
    if DEBUG:
        chain = " -> ".join("%d %s" % (h.status_code, h.url[:60]) for h in (list(r.history) + [r]))
        print("  [%s] %s" % (tag, chain))

BTN_LOGIN = "ctl00$ctl00$cphShellContent$cphShellTopContent$btnLogin"

def login(s, user, pwd):
    # 0) landing LoginOrRegistration.aspx -> "Prihlásiť sa" (WebForms postback) -> 302 IdSrv challenge
    r0 = s.get(APP_ROOT, allow_redirects=True, timeout=30)
    _dbg("0 GET app", r0)
    if "login.okte.sk" in r0.url:
        r = r0
    elif "LoginOrRegistration" in r0.url:
        f0 = form_inputs(r0.text)
        f0["__EVENTTARGET"] = BTN_LOGIN
        f0["__EVENTARGUMENT"] = ""
        # Ext.NET hiddenfield sa posiela pod ClientID (podčiarkovníky), nie UniqueID ($)
        f0["cphShellContent_cphShellTopContent_btnLoginPressed"] = "true"
        purl = urljoin(r0.url, form_action(r0.text) or r0.url)
        r = s.post(purl, data=f0, allow_redirects=True, timeout=30)
        _dbg("0b POST btnLogin", r)
    else:
        if "__VIEWSTATE" in r0.text:
            return r0            # už prihlásený
        r = r0
    if "login.okte.sk" not in r.url:
        raise SystemExit("Po kliku 'Prihlasit sa' som neskoncil na IdSrv. URL=%s" % r.url)
    # 1) IdSrv login stránka
    html_login = r.text
    act = form_action(html_login)
    if not act:
        raise SystemExit("Login: nenašiel som IdSrv login formulár (action). URL=%s" % r.url)
    login_url = urljoin(r.url, act)
    fields = form_inputs(html_login)          # obsahuje idsrv.xsrf a spol.
    if DEBUG:
        print("  login form action:", login_url, "| polia:", [k for k in fields])
    fields["username"] = user
    fields["password"] = pwd
    # 2) POST prihlasovacích údajov -> form_post stránka s id_token
    r2 = s.post(login_url, data=fields, allow_redirects=True, timeout=30)
    _dbg("2 POST creds", r2)
    fields2 = form_inputs(r2.text)
    if "id_token" not in fields2:
        raise SystemExit("Login ZLYHAL (zlé heslo alebo iný formát). URL=%s" % r2.url)
    act2 = form_action(r2.text)
    post_url = urljoin(r2.url, act2 or APP_ROOT)
    if DEBUG:
        print("  id_token form -> POST na:", post_url, "| polia:", [k for k in fields2])
    # 3) POST id_token do appky -> app session cookie
    r3 = s.post(post_url, data=fields2, allow_redirects=True, timeout=30)
    _dbg("3 POST id_token", r3)
    return r3

def verify(s):
    r = s.get(CM_URL, allow_redirects=True, timeout=30)
    ok = ("__VIEWSTATE" in r.text) and ("login.okte.sk" not in r.url)
    return ok, r

# ---------------- EXPORT (Ext.NET DirectEvents) ----------------
import datetime as _dt
from zoneinfo import ZoneInfo
_TZ = ZoneInfo("Europe/Bratislava")
EXT_HDR = {"X-Ext-Net": "delta=true", "X-Requested-With": "XMLHttpRequest"}

def sk_date(d):        # date -> "1. 8. 2026"
    return "%d. %d. %d" % (d.day, d.month, d.year)

def iso_z(d):          # date -> lokálna polnoc v UTC, napr. "2026-07-31T22:00:00.000Z"
    loc = _dt.datetime(d.year, d.month, d.day, 0, 0, tzinfo=_TZ)
    return loc.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

def parse_direct(t):
    vs = re.search(r'viewState:"([^"]*)"', t)
    ev = re.search(r'eventValidation:"([^"]*)"', t)
    recs = None
    idx = t.find('{"data":')
    if idx >= 0:
        try:
            obj, _n = json.JSONDecoder().raw_decode(t[idx:])
            recs = obj.get("data")
        except Exception:
            pass
    return (vs.group(1) if vs else None), (ev.group(1) if ev else None), recs

def cm_grid_read(s, base, day_str):
    cfg = {"config": {"viewStateMode": "enabled", "extraParams": {
        "gfe_submitted": True, "gridState": None, "page": 1, "start": 0, "limit": 28,
        "sort": '[{"property":"CreatedAt","direction":"DESC"}]'}}}
    data = dict(base)
    data.update({
        "submitDirectEventConfig": json.dumps(cfg),
        "cphPluginContent_dfPeriodFrom": day_str, "cphPluginContent_dfPeriodTo": day_str,
        "cphPluginContent_cbVersion": "1", "_cphPluginContent_cbVersion_state": "",
        "cphPluginContent_cbGridMeasurementsPageSize": "Auto",
        "_cphPluginContent_cbGridMeasurementsPageSize_state": '[{"value":28,"text":"Auto","index":0}]',
        "__EVENTTARGET": "ctl00$resourceManager",
        "__EVENTARGUMENT": "cphPluginContent_storeMeasurements|postback|read",
        "cphPluginContent_ctl35": "",
    })
    t = s.post(CM_URL, data=data, headers=EXT_HDR, timeout=40).text
    return parse_direct(t)

def find_measurement_id(s, base, eic, day):
    """Nájde Id merania pre EIC v daný deň (date). Vráti (id, vs, ev)."""
    vs, ev, recs = cm_grid_read(s, base, sk_date(day))
    if not recs:
        return None, vs, ev
    for r in recs:
        if r.get("EIC") == eic:
            return r.get("Id"), vs, ev
    return None, vs, ev

def create_export(s, base, eic, d_from, d_to, rec_id, grid_day, viewstate, eventvalidation):
    filt = json.dumps([
        {"xtype": "textfield", "path": "EIC", "value": eic},
        {"xtype": "datefield", "path": "dfPeriodFrom", "operator": "Equal", "value": iso_z(d_from)},
        {"xtype": "datefield", "path": "dfPeriodTo", "operator": "Equal", "value": iso_z(d_to)},
    ])
    cfg = {"config": {"viewStateMode": "enabled", "extraParams": {
        "filter": filt, "sort": '[{"field":"CreatedAt","direction":"DESC"}]'}}}
    data = {
        "submitDirectEventConfig": json.dumps(cfg),
        "cphPluginContent_dfPeriodFrom": sk_date(grid_day), "cphPluginContent_dfPeriodTo": sk_date(grid_day),
        "cphPluginContent_cbVersion": "Posledná verzia",
        "_cphPluginContent_cbVersion_state": '[{"value":1,"text":"Posledná verzia","index":1}]',
        "cphPluginContent_cbGridMeasurementsPageSize": "Auto",
        "_cphPluginContent_cbGridMeasurementsPageSize_state": '[{"value":28,"text":"Auto","index":0}]',
        "__EVENTTARGET": "ctl00$resourceManager",
        "__EVENTARGUMENT": "cphPluginContent_winExtendedExport_btnExportToCSV|event|Click",
        "__VIEWSTATE": viewstate, "__VIEWSTATEGENERATOR": base.get("__VIEWSTATEGENERATOR", ""),
        "__EVENTVALIDATION": eventvalidation,
        "cphPluginContent_ctl35": json.dumps([{"RecordID": rec_id, "RowIndex": 1}]),
        "gfe_EIC": eic,
        "gfe_cphPluginContent_dfPeriodFrom_on": sk_date(d_from),
        "gfe_cphPluginContent_dfPeriodTo_on": sk_date(d_to),
    }
    for k in ("gfe_Meaning", "_gfe_Meaning_state", "gfe_MeasurementKind", "_gfe_MeasurementKind_state",
              "gfe_SubstitutedValues", "_gfe_SubstitutedValues_state", "gfe_Version_eq", "gfe_Version_gt",
              "gfe_Version_lt", "gfe_AggregatedValue_eq", "gfe_AggregatedValue_gt", "gfe_AggregatedValue_lt",
              "gfe_CreatedAt_eq", "gfe_CreatedAt_gt", "gfe_CreatedAt_lt", "gfe_PowerGridName",
              "gfe_PowerGridEIC", "gfe_Participant"):
        data[k] = ""
    t = s.post(CM_URL, data=data, headers=EXT_HDR, timeout=40).text
    return t

import time
EXPORT_URL = "https://ims.okte.sk/portal/Plugins/ISO/Pages/Export/Default.aspx"

def read_exports(s, base):
    cfg = {"config": {"viewStateMode": "enabled", "extraParams": {
        "page": 1, "start": 0, "limit": 29, "sort": '[{"property":"CreatedAt","direction":"DESC"}]'}}}
    d = dict(base); d.update({
        "submitDirectEventConfig": json.dumps(cfg),
        "cphPluginContent_cbGridExportsPageSize": "Auto",
        "_cphPluginContent_cbGridExportsPageSize_state": '[{"value":29,"text":"Auto","index":0}]',
        "__EVENTTARGET": "ctl00$resourceManager",
        "__EVENTARGUMENT": "cphPluginContent_storeExports|postback|read", "cphPluginContent_ctl24": ""})
    return parse_direct(s.post(EXPORT_URL, data=d, headers=EXT_HDR, timeout=40).text)

def view_download(s, base, rec_id, vs, ev):
    cfg = {"config": {"viewStateMode": "enabled", "extraParams": {"CommandName": "View", "ID": rec_id}}}
    d = dict(base); d.update({
        "submitDirectEventConfig": json.dumps(cfg),
        "cphPluginContent_cbGridExportsPageSize": "Auto",
        "_cphPluginContent_cbGridExportsPageSize_state": '[{"value":29,"text":"Auto","index":0}]',
        "__VIEWSTATE": vs or base["__VIEWSTATE"], "__VIEWSTATEGENERATOR": base.get("__VIEWSTATEGENERATOR", ""),
        "__EVENTVALIDATION": ev or base["__EVENTVALIDATION"],
        "__EVENTTARGET": "ctl00$resourceManager",
        "__EVENTARGUMENT": "cphPluginContent_ctl06|event|Command", "cphPluginContent_ctl24": ""})
    t = s.post(EXPORT_URL, data=d, headers=EXT_HDR, timeout=40).text
    m = re.search(r'dfid=([A-Za-z0-9_]+)', t)
    if not m:
        raise RuntimeError("nenašiel som dfid vo View odpovedi")
    url = EXPORT_URL + "?dfid=" + m.group(1)
    last = None
    for attempt in range(5):
        try:
            resp = s.get(url, timeout=90, headers={"Connection": "close"})
            if "zip" not in (resp.headers.get("content-type") or ""):
                raise RuntimeError("download nie je zip: " + str(resp.headers.get("content-type")))
            return resp.content
        except requests.exceptions.RequestException as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last

def download_export(s, exp_base, expected_name, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        vs, ev, recs = read_exports(s, exp_base)
        rec = next((r for r in (recs or []) if r.get("Name") == expected_name), None)
        if rec:
            if rec.get("HasError"):
                raise RuntimeError("export skončil chybou: " + expected_name)
            # POZOR: "Pripravuje sa" (spracováva sa) vs "Pripravené/ý" (hotové) — oba by matchli "priprav"
            st = str(rec.get("Status", "")).lower()
            if st.startswith("pripraven"):     # Pripravené / Pripravený = hotové
                time.sleep(0.5)
                return view_download(s, exp_base, rec["ID"], vs, ev)
        time.sleep(3)
    raise TimeoutError("export sa nepripravil včas: " + expected_name)

def chunks(d_from, d_to, days=62):
    cur = d_from
    while cur <= d_to:
        end = min(cur + _dt.timedelta(days=days - 1), d_to)
        yield cur, end
        cur = end + _dt.timedelta(days=1)

def alarm_check(hourly):
    """Po inkremente: ak včerajšia denná spotreba >= mult × predošlý deň -> notify."""
    if os.getenv("OKTE_ALARM", "1") != "1":
        return
    try:
        mult = float(os.getenv("OKTE_ALARM_MULT", "2.0"))
        minkwh = float(os.getenv("OKTE_ALARM_MIN", "3.0"))
    except Exception:
        mult, minkwh = 2.0, 3.0
    byday = {}
    for h, kwh in hourly:
        byday[h.date()] = byday.get(h.date(), 0.0) + kwh
    days = sorted(byday)
    if len(days) < 2:
        return
    yd, pd = days[-1], days[-2]
    y, p = byday[yd], byday[pd]
    ratio = (y / p) if p else 0.0
    if p >= minkwh and y >= mult * p:
        import import_to_ha as IMP
        title = "Zvýšená spotreba elektriny"
        msg = "Zvýšená spotreba: %s = %.1f kWh, čo je %.1f× viac ako %s (%.1f kWh)." % (yd, y, ratio, pd, p)
        try:
            IMP.call_notify(os.getenv("OKTE_NOTIFY", "notify.pushover"), title, msg)
            print("[alarm] ODOSLANÉ:", msg)
        except Exception as e:
            print("[alarm] notify zlyhalo:", e)
    else:
        print("[alarm] OK: %s=%.1f kWh, %s=%.1f kWh (pomer %.2f, prah %.1f×)" % (yd, y, pd, p, ratio, mult))

def run(eic, d_from, d_to, out_dir, do_import=True, incremental=False):
    os.makedirs(out_dir, exist_ok=True)
    u, p = load_secrets(); s = new_session(); login(s, u, p)
    print("prihlásený. hľadám Id merania pre EIC %s ..." % eic)
    cm_base = form_inputs(s.get(CM_URL, timeout=30).text)
    mid = None; gday = None
    for back in (2, 3, 4, 7, 10, 14):
        gday = _dt.date.today() - _dt.timedelta(days=back)
        mid, _v, _e = find_measurement_id(s, cm_base, eic, gday)
        if mid:
            break
    if not mid:
        raise SystemExit("Nenašiel som Id merania pre EIC (žiadne dáta v posledných dňoch?).")
    print("Id merania: %s (deň %s)" % (mid, sk_date(gday)))
    for cf, ct in chunks(d_from, d_to):
        name = "MeraniaOOMPoPeriodach_%s_%s.zip" % (sk_date(cf), sk_date(ct))
        blob = None; lasterr = None
        for att in range(4):
            try:
                cm_base = form_inputs(s.get(CM_URL, timeout=30).text)
                _mid, vs, ev = find_measurement_id(s, cm_base, eic, gday)
                create_export(s, cm_base, eic, cf, ct, mid, gday, vs or cm_base["__VIEWSTATE"], ev or cm_base["__EVENTVALIDATION"])
                time.sleep(1.0)
                exp_base = form_inputs(s.get(EXPORT_URL, timeout=30).text)
                blob = download_export(s, exp_base, name)
                break
            except Exception as e:
                lasterr = e
                print("   (pokus %d zlyhal: %s) — čakám a skúšam znova" % (att + 1, str(e)[:70]))
                time.sleep(6 * (att + 1))
        if blob is None:
            raise lasterr
        fp = os.path.join(out_dir, name.replace(" ", ""))
        open(fp, "wb").write(blob)
        print("  chunk %s .. %s  ->  %s (%d B)" % (sk_date(cf), sk_date(ct), os.path.basename(fp), len(blob)))
        time.sleep(1.5)
    # import do HA
    if not do_import:
        print("(--no-import) stiahnuté do %s, import preskočený." % out_dir); return
    import import_to_ha as IMP, asyncio
    hourly = IMP.collect_hourly([out_dir], eic)
    if not hourly:
        print("Žiadne hodinové dáta na import."); return
    base = 0.0
    if incremental:
        fh = hourly[0][0]
        first_local = _dt.datetime(fh.year, fh.month, fh.day, fh.hour, tzinfo=_TZ)
        base = asyncio.run(IMP.get_last_sum(first_local))
        print("inkrement: kotva (sum pred %s) = %.3f kWh" % (first_local.isoformat()[:16], base))
    stats = IMP.build_stats(hourly, base_sum=base)
    print("Import do HA: %d hodín, +%.1f kWh, koncový sum %.1f (od %s)" % (
        len(stats), stats[-1]["sum"] - base, stats[-1]["sum"], stats[0]["start"][:10]))
    resp = asyncio.run(IMP.send_to_ha(stats))
    print("HA import success:", resp.get("success"))
    if incremental and resp.get("success"):
        alarm_check(hourly)
    # živý senzor na zrkadlenie na druhú HA cez remote_homeassistant (voliteľné)
    ms = os.getenv("OKTE_MIRROR_SENSOR", "").strip()
    if resp.get("success") and ms:
        try:
            IMP.set_ha_sensor(ms, round(stats[-1]["sum"], 3), IMP.mirror_attrs())
            print("[mirror] senzor %s = %.1f kWh" % (ms, stats[-1]["sum"]))
        except Exception as e:
            print("[mirror] set senzora zlyhalo:", e)

def _argval(flag, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default

if __name__ == "__main__":
    if "--run" in sys.argv or "--days" in sys.argv:
        eic = _argval("--eic") or os.getenv("OKTE_EIC") or ""
        out = _argval("--out", os.path.join(HERE, "downloads"))
        if not eic:
            raise SystemExit("Chýba EIC — zadaj --eic <EIC> alebo add-on option 'eic'.")
        days_s = _argval("--days")
        if days_s:
            n = int(days_s)
            d_to = _dt.date.today() - _dt.timedelta(days=1)
            d_from = d_to - _dt.timedelta(days=n - 1)
            import shutil; shutil.rmtree(out, ignore_errors=True)
            print("INKREMENT: EIC %s | posledných %d dní (%s .. %s)" % (eic, n, d_from, d_to))
            run(eic, d_from, d_to, out, do_import=True, incremental=True)
        else:
            to_s = _argval("--to"); from_s = _argval("--from")
            d_to = _dt.date.fromisoformat(to_s) if to_s else (_dt.date.today() - _dt.timedelta(days=1))
            d_from = _dt.date.fromisoformat(from_s) if from_s else (d_to - _dt.timedelta(days=61))
            do_import = "--no-import" not in sys.argv
            print("RUN: EIC %s | %s .. %s | out=%s | import=%s" % (eic, d_from, d_to, out, do_import))
            run(eic, d_from, d_to, out, do_import)
    elif "--export-test" in sys.argv:
        DEBUG = "--debug" in sys.argv
        u, p = load_secrets()
        s = new_session(); login(s, u, p)
        base = form_inputs(s.get(CM_URL, timeout=30).text)
        eic = _argval("--eic") or os.getenv("OKTE_EIC") or ""
        gday = _dt.date.today() - _dt.timedelta(days=1)   # včera (má dáta)
        mid, vs, ev = find_measurement_id(s, base, eic, gday)
        print("grid deň:", sk_date(gday), "| Id merania pre EIC:", mid)
        if not mid:
            print("!! nenašiel som meranie pre EIC v ten deň — skús iný deň"); sys.exit(1)
        d_to = gday
        d_from = gday - _dt.timedelta(days=2)             # malý rozsah na test
        print("export period:", sk_date(d_from), "->", sk_date(d_to))
        resp = create_export(s, base, eic, d_from, d_to, mid, gday, vs or base["__VIEWSTATE"], ev or base["__EVENTVALIDATION"])
        print("--- export-create odpoveď (prvých 900) ---")
        print(resp[:900])
        print("...\nsuccess:", '"success":true' in resp or "success:true" in resp)
    elif "--login-test" in sys.argv:
        DEBUG = "--debug" in sys.argv
        u, p = load_secrets()
        s = new_session()
        print("prihlasujem sa ako:", u)
        r3 = login(s, u, p)
        print("po logine URL:", r3.url[:80])
        print("po logine 'LoginOrRegistration' v URL/texte:",
              ("LoginOrRegistration" in r3.url) or ("LoginOrRegistration" in r3.text))
        ok, r = verify(s)
        print("session cookies:", [c.name for c in s.cookies])
        print("verify GET CM URL:", r.url[:80])
        bad = "LoginOrRegistration" in r.url or "LoginOrRegistration" in r.text
        ok = ok and not bad
        print("VYSLEDOK:", "LOGIN OK" if ok else "LOGIN NEPRESIEL (skoncilo na login/registracii)")
    else:
        print("Pouzi: python okte_auto.py --login-test [--debug]")
