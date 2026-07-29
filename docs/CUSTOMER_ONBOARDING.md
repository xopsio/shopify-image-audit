# Customer Onboarding — Shopify Image Audit

> **Tarkoitus:** Vaiheittainen ohje ensimmäisen asiakkaan auditoinnin
> suorittamiseen alusta loppuun. Kohde: 99–199 € auditointitoimitus (vaihe 1).
>
> **Omistaja:** ZCode (governance v1.3, yksittäisagentti)

---

## 1. Ennen auditointia (pre-audit)

### 1.1 Tarvittavat tiedot asiakkaalta
- [ ] **Kaupan URL** (`https://kauppa.myshopify.com` tai custom-verkkotunnus)
- [ ] **Laitetyyppi**, joka kiinnostaa (mobiili on oletus; työpöytä lisäksi)
- [ ] **Shopify Admin -pääsy** (vain jos halutaan todellinen Lighthouse-ajo
      storen kautta; paikallisella JSON-syötteellä pääsyä ei tarvita)
- [ ] **Optimointikohteet**, joita asiakas epäilee (esim. "etusivu on hidas")
- [ ] **Konversiobaseline** (GA4 / Shopify Analytics: nykyinen konversioprosentti
      ja ka. tilausarvo — tarvitaan ROI-arvion tarkentamiseen)

### 1.2 Työkalun valmiustarkistus
```bash
# Kloonaa repo ja asenna (jos ei vielä tehty)
git clone https://github.com/xopsio/shopify-image-audit.git
cd shopify-image-audit
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# Vahvista asennus
audit version          # -> shopify-image-audit 0.1.0
pytest -q              # -> 219 passed (tai enemmän)
```

### 1.3 Päätä mittausstrategia
- **MVP (suositeltu ensi-asiakkaalle):** Asiakas toimii Lighthouse-raportin
  JSON-tiedostot (ennen/jälkeen), auditointi ajetaan paikallisesti.
  - Edut: deterministinen, ei verkkorajoituksia, nopea.
- **Live PageSpeed (vaihtoehto):** Työkalu hakee LCP:n suoraan Google
  PageSpeed Insights API:sta komennolla `audit measure <url>`.
  - Huom: API on nopeusrajoitettu (ilman API-avainta ~20 pyyntöä/min).

---

## 2. Auditoinnin suorittaminen

### 2.1 Vaihe A — Perustason mittaus (baseline)

Tallenna nykytila **ennen optimointeja**. Tämä on vertailukohta ROI:lle.

```bash
# Jos asiakas toimii Lighthouse-raportin (lhr.json):
audit baseline <asiakkaan_lhr.json> --save baseline.json \
    --url https://kauppa.myshopify.com --device mobile

# Jos haluat ajaa Lighthousen itse (vaatii npm i -g lighthouse):
audit run https://kauppa.myshopify.com --device mobile --runs 3 --out-dir artifacts/
audit baseline artifacts/lhr_run3.json --save baseline.json
```

**Tuloste:** `baseline.json` (validoitu `audit_result.schema.json`:ia vasten).

### 2.2 Vaihe B — Suositusten toteutus (asiakas/tiimi tekee)

Käy läpi `audit run`:n tuottamat suositukset ja toteuta ne Shopifyssa:
1. Hero/LCP-kuvan optimointi (WebP/AVIF, oikea resoluutio)
2. Modernit muodot kaikille kuville
3. Lazy-loading taiton alapuolelle
4. [katso `docs/CUSTOMER_REPORT_TEMPLATE.md` §4]

### 2.3 Vaihe C — Uudelleenmittaus optimoinnin jälkeen

```bash
# Mittaa uusi tila samalla laitteella
audit baseline <asiakkaan_uusi_lhr.json> --save after.json \
    --url https://kauppa.myshopify.com --device mobile
```

### 2.4 Vaihe D — Vertailu ja raportti

```bash
# Vertaa ja tuota asiakasraportti (HTML + JSON)
audit compare baseline.json after.json \
    -o audit_report.html --json comparison.json
```

**Tuloste:**
- `audit_report.html` — koko tekninen raportti + ennen/jälkeen-osio
- `comparison.json` — koneluettava vertailudata

---

## 3. Toimitus asiakkaalle

### 3.1 Toimitettavat tiedostot
1. **Asiakasraportti** (`CUSTOMER_REPORT_TEMPLATE.md` pohjalla täytetty)
2. **HTML-raportti** (`audit_report.html`)
3. **Vertailudata** (`comparison.json`)

### 3.2 Toimitusmuoto
- Suositeltu: PDF raportista + HTML-liitteenä (HTML on interaktiivisempi)
- Vaihtoehto: jaettava kansio (Drive/Dropbox) kaikilla tiedostoilla

### 3.3 Esimerkkitoimitus
Katso valmis demotoimitus: `docs/examples/`
- `demo_audit_report.html` — täysi tekninen raportti (Nordic Lifestyle -demokauppa)
- `demo_comparison.json` — vertailudata (LCP 4200→1800ms, −57 %)

---

## 4. Seuranta ja uudelleenmittaus

| Aikataulu | Toimenpide |
|-----------|-----------|
| Heti toimituksen jälkeen | Palaveri suositusten läpikäymiseksi |
| +1–2 viikkoa | Optimointien toteutuksen tarkistus |
| +2–4 viikkoa | Uudelleenmittaus (`audit compare`) + päivitetty raportti |
| Jatkuva | Kuukausittain CrUX/GA4-konversion seuranta |

---

## 5. Yleiset ongelmat ja ratkaisut

| Ongelma | Ratkaisu |
|---------|----------|
| Lighthouse ei asennu | Käytä asiakkaan toimittamaa LHR-JSONia (ei vaadi lighthouse-asennusta) |
| Mittaukset vaihtelevat paljon | Aja 3 kertaa, käytä mediaania (katso `docs/runbook/measurement_protocol.md`) |
| LCP = 0 / vitals puuttuvat | Varmista että LHR sisältää `metrics`-audion tai ylätason `lcp_ms`-avaimet |
| `compare` kaatuu "Extra inputs" | Syötä joko tallennettu `audit_result.json` TAI raaka LHR — työkalu käsittelee molemmat automaattisesti |
| Polkuvirhe (`--output must be relative`) | Työkalu estää absoluuttiset polut tietoturvasyistä; käytä suhteellisia polkuja työhakemistossa |

---

## 6. Hinnotteluohje (vaihe 1)

| Toimitus | Suositeltu hinta |
|----------|------------------|
| Kertaa-auditointi (ennen) | 99 € |
| Ennen/jälkeen -auditointi (täysi työnkulku) | 149–199 € |
| Kuukausittainen uudelleenmittaus (tilaus) | `[määritellään myöhemmin]` |

> Hinnoittelu perustuu vaihe 1 -roadnappiin. Arvo perustuu todistettavaan
> ROI-arvioon (LCP-parannus → arvioitu konversioparannus).

---

*Omistaja: ZCode · Päivitetty: 2026-07-30*
