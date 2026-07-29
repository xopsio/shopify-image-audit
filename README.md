# Shopify Image Audit

Työkalu Shopify-kuvien suorituskyvyn auditointiin ja optimointisuosituksiin Lighthouse-pohjaisesti.

## Governance & Domain Division

Projektin domain-jako, omistajuus ja kehitysperiaatteet on dokumentoitu tiedostoon  
[docs/governance.md](docs/governance.md).

## Asennus & Käyttö

```bash
git clone https://github.com/xopsio/shopify-image-audit.git
cd shopify-image-audit
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# Komentoja
audit run https://kauppa.myshopify.com --device mobile      # Lighthouse-ajo + analyysi
audit baseline <lhr.json> --save baseline.json              # tallenna perustaso
audit compare baseline.json <current.json> -o report.html   # ennen/jälkeen -vertailu
audit report <audit_result.json> -o report.html             # HTML-raportti
```

Kattava käyttöohje ja komentojen erittely: [CLI Specification](docs/spec/cli_v0_1.md).

## Asiakastoimitukset (vaihe 1)

- [Asiakasraporttipohja](docs/CUSTOMER_REPORT_TEMPLATE.md) — myyntiartefakti
- [Asiakas-onboarding](docs/CUSTOMER_ONBOARDING.md) — auditoinnin työnkulku alusta loppuun
- [Esimerkkiasiakasraportti](docs/examples/demo_audit_report.html) — Nordic Lifestyle -demokauppa

## Lisätietoa

- [QA Checklist](QA_CHECKLIST.md)
- [CLI Specification](docs/spec/cli_v0_1.md)
- [Measurement Protocol](docs/runbook/measurement_protocol.md)
- [Governance](docs/governance.md)
- [Sprint 2 Plan](docs/SPRINT_2_PLAN.md)
