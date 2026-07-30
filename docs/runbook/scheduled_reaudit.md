# Scheduled Re-audit Runbook

This runbook shows how to set up **automated recurring audits** for your
Shopify stores. The model is deliberately simple: the tool handles
*what to audit*, and your host's cron / systemd timer handles *when*.

## How it works

```
crontab / systemd timer
        │
        ▼
audit schedule run-all          ← reads ~/.shopify-image-audit/schedules.json
        │
        ├─ fetches each store via PageSpeed Insights API
        ├─ records each AuditResult to HistoryStore
        └─ prints a per-store summary
```

No daemon, no background process. Each cron invocation is a one-shot.

---

## 1. Add a schedule

```bash
audit schedule add mystore.myshopify.com https://mystore.myshopify.com \
    --device mobile \
    --label "Daily 09:00"
```

This appends an entry to `~/.local/share/.shopify-image-audit/schedules.json`.
Repeat for each store you want to monitor.

### List configured schedules

```bash
audit schedule list
```

### Remove a schedule

```bash
audit schedule remove mystore.myshopify.com
```

---

## 2. Test the run manually

```bash
audit schedule run-all --api-key YOUR_PAGESPEED_KEY
```

You should see output like:

```
  ✓ mystore.myshopify.com: recorded (id=a1b2c3d4e5f6)
  ✓ otherstore.myshopify.com: recorded (id=f6e5d4c3b2a1)
```

Failures are surfaced in red and do **not** abort the rest of the run.

---

## 3. Set up cron (Linux / macOS)

Edit your crontab:

```bash
crontab -e
```

Add a line for daily audits at 09:00:

```cron
# Run Shopify image audits daily at 09:00
0 9 * * * /usr/local/bin/audit schedule run-all --api-key YOUR_KEY >> /var/log/shopify-audit.log 2>&1
```

### Weekly instead of daily

```cron
# Every Monday at 09:00
0 9 * * 1 /usr/local/bin/audit schedule run-all --api-key YOUR_KEY >> /var/log/shopify-audit.log 2>&1
```

### Prevent overlapping runs with `flock`

If an audit takes longer than the schedule interval, use `flock` to
prevent concurrent invocations:

```cron
0 9 * * * /usr/bin/flock -n /tmp/shopify-audit.lock /usr/local/bin/audit schedule run-all --api-key YOUR_KEY >> /var/log/shopify-audit.log 2>&1
```

---

## 4. systemd timer alternative (Linux)

For more robust scheduling with logging and retries, use a systemd timer.

`~/.config/systemd/user/shopify-audit.service`:

```ini
[Unit]
Description=Shopify Image Audit (scheduled)

[Service]
Type=oneshot
ExecStart=/usr/local/bin/audit schedule run-all --api-key YOUR_KEY
StandardOutput=journal
StandardError=journal
```

`~/.config/systemd/user/shopify-audit.timer`:

```ini
[Unit]
Description=Run Shopify Image Audit daily at 09:00

[Timer]
OnCalendar=*-*-* 09:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable:

```bash
systemctl --user daemon-reload
systemctl --user enable --now shopify-audit.timer
```

Inspect runs:

```bash
journalctl --user -u shopify-audit.service
```

---

## 5. Review trends

After a few scheduled runs, view the accumulated history:

```bash
# List all recorded snapshots
audit history list mystore.myshopify.com

# Generate a trend HTML
audit history show mystore.myshopify.com -o trend.html

# Diff two snapshots
audit history diff mystore.myshopify.com --from <id1> --to <id2> -o diff.html
```

---

## 6. Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `WARNING` | Logging level (`DEBUG` for verbose output) |
| `XDG_DATA_HOME` | `~/.local/share` | Base dir for schedules.json + history/ |
| `PAGESPEED_CACHE_TTL` | `3600` | PageSpeed response cache TTL in seconds (`0` disables) |

---

## 7. Security notes

- `schedules.json` may contain `access_token` values (only needed if you
  also run Shopify inventory via the same config). Protect the file:

  ```bash
  chmod 600 ~/.local/share/.shopify-image-audit/schedules.json
  ```

- The PageSpeed API key is passed via `--api-key` on the command line.
  For cron, consider storing it in an env file sourced by the crontab,
  or use a wrapper script with `0600` permissions.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `No schedules configured` | Run `audit schedule add <domain> <url>` first |
| `Backend failure: ...` | PageSpeed API rate-limited; add `--api-key` or wait |
| Empty history after run-all | Check `--history-dir` points to the same dir as `audit history list` |
| Cron runs overlap | Add `flock -n /tmp/lock` (see §3) |