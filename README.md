# OKTE IMS – Home Assistant add-on

Home Assistant add-on, ktorý importuje spotrebu elektriny z portálu **OKTE IMS**
(`ims.okte.sk`) do Home Assistant *long-term statistics* — použiteľné v **Energy dashboarde**.

OKTE je národný hub inteligentného merania (IMS) na Slovensku; portál dáva rovnaké
15-minútové namerané dáta ako distribučný portál, ale prihlásenie je len meno + heslo
(bez reCaptcha).

## Čo to robí
- Prihlási sa na `ims.okte.sk` a stiahne 15-min priebehové merania (funkcia *Export po periódach*).
- Prepočíta ich na hodinové kWh a naimportuje ako long-term statistics.
- Beží denne — každý beh stiahne posledných *N* dní a doplní ich; kumulatívny súčet
  nadviaže na existujúcu históriu (`recorder/import_statistics`).
- Voliteľný alarm: upozorní, keď je denná spotreba ≥ *N×* vyššia ako predchádzajúci deň.

## Inštalácia
1. Home Assistant → **Nastavenia → Doplnky → Obchod s doplnkami → ⋮ → Repozitáre**.
2. Pridaj URL tohto repozitára: `https://github.com/valdaaak/hass-okte-ims`
3. V obchode nainštaluj **OKTE IMS Import**.
4. Vyplň konfiguráciu (nižšie) a spusti add-on. Odporúčam zapnúť *Spustiť pri štarte* + *Watchdog*.
5. Pridaj štatistiku do Energy dashboardu: **Nastavenia → Energia → Sieťová spotreba → Pridať spotrebu**.

## Konfigurácia
| Voľba | Predvolené | Popis |
|---|---|---|
| `okte_username` | — | Prihlasovacie meno na ims.okte.sk |
| `okte_password` | — | Heslo na ims.okte.sk |
| `eic` | — | EIC kód odberného miesta |
| `statistic_id` | `okte:elektrina_spotreba` | ID štatistiky v HA (musí obsahovať `:`) |
| `statistic_name` | `OKTE IMS – spotreba zo siete` | Zobrazovaný názov štatistiky |
| `backfill_days` | `14` | Koľko posledných dní stiahnuť pri každom behu (1–62) |
| `run_hour` | `6` | Hodina denného behu (Europe/Bratislava, 0–23) |
| `alarm_enabled` | `true` | Zapnúť alarm na nárast spotreby |
| `alarm_multiplier` | `2.0` | Prah alarmu (× predchádzajúci deň) |
| `alarm_min_kwh` | `3.0` | Ignorovať nárasty pod touto dennou hodnotou |
| `notify_service` | `notify.pushover` | HA notify služba pre alarm |
| `ha_token` | — | Long-lived token HA (potrebný, ak Supervisor add-onu token neposkytne) |
| `ha_ws_url` | *(auto)* | Ručné prepísanie WebSocket URL do HA |
| `mirror_sensor` | — | Voliteľný živý senzor (napr. `sensor.okte_elektrina_spotreba`) s kumulatívom kWh na zrkadlenie do inej HA cez remote_homeassistant. Senzor zapísaný cez REST reštart HA neprežije, preto ho add-on každých 5 min kontroluje a po reštarte HA obnoví z poslednej hodnoty štatistiky. |

## Historický backfill
Denný beh sťahuje len posledné dni. Na natiahnutie celej histórie sa dá jednorazovo
spustiť pribalený skript:

```
python okte_auto.py --run --from 2025-01-01 --to 2026-09-08 --eic <EIC>
```

## Ako to funguje
Portál `ims.okte.sk` beží na platforme sfera XMtrade (ASP.NET / Ext.NET). Add-on replikuje
tok prehliadača: OIDC prihlásenie → vytvorenie exportného jobu → polling kým je hotový →
stiahnutie ZIP-u. 15-min hodnota je priemerný výkon v kW; hodinové kWh = Σ(kW × 0,25) —
denný súčet sedí s denným súhrnom OKTE. Import ide cez `recorder/import_statistics`.

Dáta sú dostupné s ~1-dňovým oneskorením (D+1).

## Súbory
- `okte_ims/` – samotný add-on (Dockerfile, config, skripty)
- `okte_ims/okte_auto.py` – login + export + download + orchestrácia
- `okte_ims/parse_ims.py` – parser OKTE CSV (denný súhrn aj 15-min)
- `okte_ims/import_to_ha.py` – prepočet na hodinové kWh + import do HA
- `okte_ims/run.py` – entrypoint add-onu (denný scheduler)
