# OKTE IMS → Home Assistant

Home Assistant **add-on repozitár** — denný import spotreby elektriny z **OKTE IMS**
(`ims.okte.sk`) do Home Assistant long-term statistics / Energy dashboardu.

## Inštalácia
1. Home Assistant → **Nastavenia → Doplnky → Obchod s doplnkami → ⋮ (vpravo hore) → Repozitáre**.
2. Pridaj URL tohto repozitára a zavri.
3. V obchode sa objaví **OKTE IMS Import** → **Inštalovať**.
4. V záložke **Konfigurácia** vyplň `okte_username`, `okte_password`, `eic` a `ha_token`
   (long-lived token z tvojej HA: Profil → Zabezpečenie → Tokeny s dlhou platnosťou).
5. **Spusti** add-on.

Detaily a všetky voľby v [okte_ims/README.md](okte_ims/README.md).

## Ako to funguje
- Prihlási sa na ims.okte.sk (len meno + heslo, bez reCaptcha), stiahne 15-min priebehové
  merania (Export po periódach), spočíta hodinové kWh a naimportuje ich ako long-term statistics.
- Denný inkrement nadväzuje kumulatívny súčet na existujúcu históriu.
- Voliteľný alarm pri náraste dennej spotreby (≥ N× predošlý deň) cez HA `notify` službu.

## Bezpečnosť
- **Žiadne credentials v repozitári** — meno, heslo, EIC a token sa zadávajú len v nastaveniach
  add-onu a zostávajú lokálne v tvojej Home Assistant inštalácii.
