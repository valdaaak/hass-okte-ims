# OKTE IMS Import (Home Assistant add-on)

Denne stiahne 15-min spotrebu elektriny z **OKTE IMS** (`ims.okte.sk`) a naimportuje ju
do Home Assistant ako **long-term statistics** — použiteľné v **Energy dashboarde**.

- Prihlásenie na OKTE je len meno+heslo (bez reCaptcha).
- 15-min priemerný výkon (kW) → hodinové kWh → kumulatívny súčet naviazaný na existujúcu históriu.
- Import ide do lokálnej HA cez supervisor proxy (`SUPERVISOR_TOKEN`), netreba žiadny token.

## Nastavenia (Configuration)

| Voľba | Popis |
|---|---|
| `okte_username` | Prihlasovacie meno na ims.okte.sk |
| `okte_password` | Heslo na ims.okte.sk |
| `eic` | EIC kód tvojho odberného miesta (nájdeš v OKTE IMS / na zmluve) |
| `statistic_id` | ID štatistiky v HA (musí obsahovať `:`, napr. `okte:elektrina_spotreba`) |
| `statistic_name` | Zobrazovaný názov štatistiky |
| `backfill_days` | Koľko posledných dní stiahnuť pri každom behu (1–62, default 14) |
| `run_hour` | Hodina denného behu, Europe/Bratislava (0–23, default 6) |
| `ha_ws_url` | WebSocket HA (default `ws://supervisor/core/websocket`) |

## Použitie
1. Vyplň `okte_username`, `okte_password`, `eic`.
2. Štart add-onu → v logu sledovať prvý beh.
3. V HA: **Nastavenia → Energia → Sieťová spotreba → Pridať spotrebu** → vyber svoju štatistiku.

Prvý (full) backfill histórie sa robí zvlášť skriptom `okte_auto.py --run --from … --to …`.
