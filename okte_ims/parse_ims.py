# -*- coding: utf-8 -*-
"""
Parser OKTE IMS exportov (ims.okte.sk).
Autodetekcia 2 typov CSV podľa hlavičky:
  A) denný súhrn   : "...;Sumárne množstvo (kWh);..."                      -> {eic: [{date,kwh,version}]}
  B) 15-min po per.: "OOM (EIC);Dátum a čas;Perióda;Množstvo (kW);..."     -> {eic: [{dt,perioda,kw,kwh}]}
Formát: ; oddeľovač, UTF-8(-sig), desatinná ČIARKA, dátum "DD. MM. YYYY".
15-min: čas = polnoc dňa + (perióda-1)*15 min; kWh = kW * 0.25.
"""
import sys, os, io, zipfile, csv, datetime

def _num(s):
    s = (s or "").strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    return float(s) if s not in ("", "-") else None

def _date(s):
    p = [x.strip() for x in (s or "").strip().split(".") if x.strip() != ""]
    return datetime.date(int(p[2].split()[0]), int(p[1]), int(p[0]))

def read_csv_text(path):
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".csv")]
            return {n: z.read(n).decode("utf-8-sig") for n in names}
    return {os.path.basename(path): io.open(path, "r", encoding="utf-8-sig").read()}

def _col(header, *needles):
    for i, h in enumerate(header):
        hl = h.lower()
        if any(n in hl for n in needles):
            return i
    return None

def parse_text(text):
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    header = rows[0]
    hset = ";".join(header).lower()
    data = [r for r in rows[1:] if r and any(c.strip() for c in r)]

    if "sumárne množstvo" in hset:
        eic_i = _col(header, "eic"); day_i = _col(header, "obchodný deň", "deň")
        kwh_i = _col(header, "sumárne množstvo"); ver_i = _col(header, "verzia")
        out = {}
        for r in data:
            eic = r[eic_i].strip()
            out.setdefault(eic, []).append({"date": _date(r[day_i]), "kwh": _num(r[kwh_i]),
                                            "version": r[ver_i].strip() if ver_i is not None else None})
        return ("daily", out)

    if "perióda" in hset:
        eic_i = _col(header, "eic"); date_i = _col(header, "dátum"); per_i = _col(header, "perióda")
        kw_i = _col(header, "množstvo", "kw")
        out = {}
        for r in data:
            eic = r[eic_i].strip() if eic_i is not None else "?"
            d = _date(r[date_i]); per = int(r[per_i]); kw = _num(r[kw_i])
            dt = datetime.datetime(d.year, d.month, d.day) + datetime.timedelta(minutes=15 * (per - 1))
            out.setdefault(eic, []).append({"dt": dt, "perioda": per, "kw": kw,
                                            "kwh": (kw * 0.25 if kw is not None else None)})
        return ("interval15", out)

    return ("unknown", {"header": header})

def parse(path):
    """Vráti (kind, {eic: [...]}) zlúčené cez všetky CSV v zipe."""
    kind = None; merged = {}
    for name, text in read_csv_text(path).items():
        k, res = parse_text(text)
        kind = k
        if k in ("daily", "interval15"):
            for eic, rows in res.items():
                merged.setdefault(eic, []).extend(rows)
    return (kind, merged)

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else \
        r"C:\Users\valde\Claude\output\Tech\okte-ims\sample\MeraniaOOMPoPeriodach_6._9._2026_8._9._2026.zip"
    kind, res = parse(path)
    print("typ exportu:", kind)
    for eic, rows in res.items():
        print("\n=== OM %s ===" % eic)
        if kind == "daily":
            for d in rows:
                print("   %s  v%s  %.3f kWh" % (d["date"], d["version"], d["kwh"]))
        elif kind == "interval15":
            byday = {}
            for x in rows:
                byday.setdefault(x["dt"].date(), 0.0)
                byday[x["dt"].date()] += (x["kwh"] or 0.0)
            print("   intervalov: %d" % len(rows))
            for day in sorted(byday):
                n = sum(1 for x in rows if x["dt"].date() == day)
                print("   %s : %d periód, spolu %.3f kWh" % (day, n, byday[day]))
            # ukážka prvých pár + hodinová agregácia prvej hodiny
            print("   prvé 3 intervaly:")
            for x in rows[:3]:
                print("      %s  per=%s  %.4f kW  -> %.4f kWh" % (x["dt"].strftime("%Y-%m-%d %H:%M"), x["perioda"], x["kw"], x["kwh"]))
