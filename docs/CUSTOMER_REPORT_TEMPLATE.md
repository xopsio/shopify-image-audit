# Shopify Image Audit — Customer Report Template

> **Käyttötarkoitus:** Tämä on runkopohja asiakkaalle toimitettavaa auditointiraporttia
> varten. Korvaa `[hakasulkeissa]` olevat kohdat asiakkaan tiedoilla ja oikealla
> mitatusu datalla. Raportin hintatavoite: 99–199 € (vaihe 1).
>
> **Lähde:** Auditointi tuotetaan `shopify-image-audit` -työkalulla
> (`audit run` + `audit baseline` / `audit compare`). Reaalidata tulee
> `docs/examples/demo_audit_report.html`:n kaltaisesta HTML-raportista ja
> `docs/examples/demo_comparison.json`:n kaltaisesta vertailudatasta.

---

## 1. Tiivistelmä (Executive Summary)

**Asiakas:** `[Kaupan nimi / verkkotunnus]`
**Auditointipäivä:** `[YYYY-MM-DD]`
**Laite:** `[mobiili | työpöytä | molemmat]`
**Auditoitu URL:** `[https://kauppa.myshopify.com]`

`[1–2 virkkeen yhteenveto: miksi kuvaoptimointi on tärkeää juuri tälle asiakkaalle ja
mikä oli suurin löytö. Esim: "Etusivun hero-kuva on 1.2 MB JPEG, joka hidastaa
LCP-arvoa 4.2 sekuntiin mobiilissa — tämä on suurin yksittäinen konversiota
heikentävä tekijä."]`

**Keskeiset tulokset (ennen → jälkeen optimoinnin):**

| Mittari | Ennen | Jälkeen | Muutos |
|---------|-------|---------|--------|
| LCP (Largest Contentful Paint) | `[4200ms]` | `[1800ms]` | `[−57 %]` |
| Kuvien kokonaiskoko | `[1587 KB]` | `[136 KB]` | `[−91 %]` |
| Arvioitu hävikki (waste) | `[1570 KB]` | `[85 KB]` | `[−1451 KB]` |
| Keskimääräinen kuvapisteet | `[10]` | `[57]` | `[+47]` |

**Arvioitu kaupallinen vaikutus:** `[esim. "LCP-parannus 2400 ms vastaa heuristiikan
mukaan n. 24 % konversioparannusta (~1 % per 100 ms). Todellinen vaikutus tulee
mitata asiakkaan analytiikasta optimoinnin jälkeen."]`

---

## 2. Mittausmenetelmä ja luotettavuus

- **Työkalu:** shopify-image-audit (Lighthouse-pohjainen)
- **Mittausprotokolla:** Katso `docs/runbook/measurement_protocol.md` (3 ajokertaa,
  mediaani, deterministinen laitteen asetus)
- **Core Web Vitals -kynnysarvot (Google):**
  - LCP: hyvä ≤ 2500 ms, kehno > 4000 ms
  - CLS: hyvä ≤ 0.1, kehno > 0.25
  - INP: hyvä ≤ 200 ms, kehno > 500 ms
- **Huom:** Luvut ovat laboratoriomittauksia (Lighthouse). Arvioi aina myös
  asiakkaan field-data (CrUX / GA4) ennen suosituksia.

---

## 3. Ennen/jälkeen -vertailu

> Liitä tähän `audit compare` -komennon tuottama vertailu. Esimerkki oikeasta
> datasta löytyy tiedostosta `docs/examples/demo_comparison.json`.

### 3.1 Core Web Vitals

| Mittari | Ennen | Jälkeen | Δ | Arvio |
|---------|-------|---------|---|-------|
| LCP | `[4200 ms]` | `[1800 ms]` | `[−2400 ms (−57 %)]` | `[parani]` |
| CLS | `[0.18]` | `[0.04]` | `[−0.14 (−78 %)]` | `[parani]` |
| INP | `[320 ms]` | `[180 ms]` | `[−140 ms (−44 %)]` | `[parani]` |
| TTFB | `[900 ms]` | `[620 ms]` | `[−280 ms (−31 %)]` | `[parani]` |

### 3.2 Kuvatason optimointi

| Mittari | Ennen | Jälkeen | Δ |
|---------|-------|---------|---|
| Kuvien määrä | `[3]` | `[3]` | `[0]` |
| Kokonaiskoko | `[1587 KB]` | `[136 KB]` | `[−1451 KB]` |
| Arvioitu hävikki | `[1570 KB]` | `[85 KB]` | `[−1451 KB]` |
| Kuvien ka. pisteet (0–100) | `[10]` | `[57]` | `[+47]` |

---

## 4. Priorisoidut suositukset (vaikutuksen mukaan)

Järjestä suositukset arvioidun vaikutuksen mukaan (suurin ensin). Jokainen
suositus sisältää: ongelman, korjauksen ja odotetun vaikutuksen.

### 4.1 `[KRIITTINEN]` Hero/LCP-kuva optimointi
- **Ongelma:** `[Hero-kuva on 1.2 MB JPEG (2400×1200), näytetään 1200×600.
  Liian suuri resoluutio + vanhentunut muoto.]`
- **Korjaus:** `[Muunna WebP/AVIF-muotoon, skaalaa näytettävään kokoon (1200×600),
  aseta responsiivinen srcset.]`
- **Odotettu vaikutus:** `[Suurin yksittäinen LCP-parannus; hero vastaa usein
  >50 % LCP-arvosta.]`

### 4.2 `[KORKEA]` Modernit kuvamuodot (WebP/AVIF)
- **Ongelma:** `[N kuvaa käyttää JPEG/PNG-muotoa vanhentuneen pakkauksen vuoksi.]`
- **Korjaus:** `[Muunna kaikki kuvat WebP (fallback JPEG) tai AVIF -muotoon.]`
- **Odotettu vaikutus:** `[25–50 % tiedostokoon pieneneminen ilman laadun
  heikkenemistä.]`

### 4.3 `[KESKISUURI]` Lazy-loading alle taiton
- **Ongelma:** `[Tuotekuvat ja logot latautuvat välittömästi, vaikka ne ovat
  taiton alapuolella.]`
- **Korjaus:** `[Lisää loading="lazy" taiton alapuolisiin kuviin.]`
- **Odotettu vaikutus:** `[Vähentää alustavaa latausta ja parantaa INP/FCP-arvoja.]`

### 4.4 `[MATKÄLLA]` `[muut kohdat...]`

---

## 5. ROI-arvio ja mittausmenetelmä

**Menetelmä (läpinäkyvä arvio, ei takuu):**
LCP-parannuksen ja konversioparannuksen suhde perustuu laajasti siteerattuun
Google/SOASTA-tutkimukseen: heuristisesti n. **1 % konversioparannus per 100 ms
LCP-parannus**. Tämä on *arvio*, joka vaihtelee toimialan, liikenteen ja
laitteen mukaan.

**Tämän auditoinnin arvio:**
- LCP-parannus: `[2400 ms]`
- Arvioitu konversioparannus: `[~24 %]` (heuristiikka)
- `[Valinnainen: laske €-vaikutus asiakkaan ka. tilausarvon ja konversioprosentin
  perusteella. Esim. "Nykyinen konversio 2.0 % → arvio 2.48 %, tilausarvo 80 € →
  +38 € per 1000 kävijää."]`

**Toimenpiteet tuloksen validointiin:**
1. Ota LCP-mittaus talteen ennen optimointia (tämä auditointi = perustaso)
2. Toteuta suositukset
3. Mittaa uudelleen `audit compare` -komennolla
4. Vertaa CrUX/GA4-konversiodataa 2–4 viikkoa optimoinnin jälkeen

---

## 6. Liitteet

- **HTML-raportti:** `[audit_report.html]` (koko yksityiskohtainen tekninen raportti)
- **Vertailudata:** `[comparison.json]` (koneluettava ennen/jälkeen-data)
- **Raakadata:** `[audit_result.json]` (validoitu skeemaa vasten)

> Esimerkki valmiista liitteistä: `docs/examples/demo_audit_report.html` ja
> `docs/examples/demo_comparison.json` (Nordic Lifestyle -demokauppa).

---

## 7. Seuraavat askeleet

1. `[Käy suositukset läpi asiakkaan kanssa (palaveri tai dokumenttikommentit)]`
2. `[Toteuta KRIITTINEN ja KORKEA -prioriteetit ensin]`
3. `[Uudelleenmittaus 1–2 viikon kuluttua]`
4. `[Toimita päivitetty ennen/jälkeen-raportti]`

---

*Laatinut: `[nimi/agentti]` · Päivitetty: `[YYYY-MM-DD]`*
*Tämä raportti perustuu työkalun tuottamaan dataan; kaupalliset arviot ovat
heuristiikkoja ja tulee validoida asiakkaan omasta analytiikasta.*
