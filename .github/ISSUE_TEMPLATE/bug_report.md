---
name: Bug report
about: Report a crash, wrong output, or unexpected behaviour
title: "[BUG] "
labels: bug
assignees: ""
---

## Bug description

<!-- What happened, and what did you expect to happen instead? -->

## Reproduction

<!-- The exact command(s) you ran. Redact any real API keys / access tokens. -->

```bash
audit run https://your-store.myshopify.com ...
```

## Expected vs actual

- **Expected:** …
- **Actual:** …

## Environment

- **audit version:** <!-- `audit --version`, or `pip show shopify-image-audit` -->
- **Install method:** <!-- pipx / pip / pip install --user / source checkout -->
- **Python version:** <!-- `python --version` -->
- **OS:** <!-- e.g. Ubuntu 24.04, macOS 15, Windows 11 -->
- **PDF export in use?** <!-- yes/no — only if the bug touches `report --pdf` -->

## Logs

<!-- Include relevant output. Run with LOG_LEVEL=INFO/DEBUG if the bug is
related to fetching or caching. -->

```text

```

## Additional context

<!-- Anything else: store size, page URL pattern, frequency of the issue… -->
