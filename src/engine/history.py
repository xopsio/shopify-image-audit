"""
Local-filesystem audit history store (Sprint 4, TD-4).

Persists ``AuditResult`` snapshots to ``~/.shopify-image-audit/history/<hostname>/``
so users can view past audits and trends over time.

Directory layout::

    ~/.shopify-image-audit/history/
        mystore.myshopify.com/
            2026-07-30T15-00-00Z.json
            2026-07-23T10-30-00Z.json
        another-store.myshopify.com/
            ...

Design notes
------------
- Each snapshot is a standalone, schema-compliant ``AuditResult`` JSON file.
- The hostname is derived from the audit URL (not user-supplied) so the same
  physical store always maps to the same directory.
- A cap (``_MAX_ENTRIES``) prevents unbounded growth; the oldest entries are
  pruned when a new one is recorded.
- The store is a pure filesystem abstraction — it has no knowledge of the CLI
  or HTML reporting. The ``HistoryEntry`` model is a lightweight index used by
  callers (e.g. the ``audit history list`` command) to avoid loading every
  snapshot.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel

from audit.models import AuditResult

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Maximum number of snapshots kept per hostname. Oldest entries are pruned
#: when a new snapshot pushes past this limit.
_MAX_ENTRIES = 100

#: Default subdirectory under $XDG_DATA_HOME (or ~/.local/share).
_HISTORY_RELATIVE = Path(".shopify-image-audit") / "history"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_hostname(url: str) -> str:
    """Extract the hostname from a store URL.

    Examples:
        ``https://mystore.myshopify.com`` → ``mystore.myshopify.com``
        ``https://mystore.myshopify.com/`` → ``mystore.myshopify.com``
    """
    parsed = urlparse(url)
    hostname = parsed.hostname or url
    # Strip trailing dots (rare but possible)
    return hostname.rstrip(".")


def _default_history_dir() -> Path:
    """Return the default history base directory.

    Respects ``$XDG_DATA_HOME`` (spec) and falls back to
    ``~/.local/share/`` for Linux, ``~/Library/Application Support/`` for
    macOS, or ``~/.shopify-image-audit/`` next to the home dir for Windows
    compat.
    """
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        base = Path(xdg)
    else:
        home = Path.home()
        # macOS convention
        if (home / "Library" / "Application Support").is_dir():
            base = home / "Library" / "Application Support"
        else:
            base = home / ".local" / "share"
    return base / _HISTORY_RELATIVE


# ---------------------------------------------------------------------------
# Entry model
# ---------------------------------------------------------------------------

class HistoryEntry(BaseModel):
    """Lightweight index entry for a single historical snapshot.

    This is NOT stored as a separate file — it is derived from the snapshot
    JSON file's ``meta`` and ``vitals`` fields by ``list_entries()``.
    """

    hostname: str
    timestamp_utc: str
    url: str
    device: str
    label: str | None = None
    path: str  # relative path within the store (hostname/<ts>.json)

    # Summary vitals for quick display (no need to load the full snapshot).
    lcp_ms: float = 0.0
    cls: float = 0.0
    inp_ms: float = 0.0
    ttfb_ms: float = 0.0
    image_count: int = 0
    total_bytes: int = 0
    avg_score: float = 0.0


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class HistoryStore:
    """Filesystem-backed history store for ``AuditResult`` snapshots.

    Usage::

        store = HistoryStore()
        store.record(result)
        entries = store.list_entries("mystore.myshopify.com")
        latest = store.latest("mystore.myshopify.com")
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        """Initialise the store.

        Args:
            base_dir: Override the default history directory. Useful for
                tests (pass a ``tmp_path``).
        """
        self._base = Path(base_dir) if base_dir else _default_history_dir()

    @property
    def base_dir(self) -> Path:
        """The resolved history root directory."""
        return self._base

    # ------------------------------------------------------------------
    # record
    # ------------------------------------------------------------------

    def record(
        self,
        audit_result: AuditResult,
        *,
        hostname: str | None = None,
        label: str | None = None,
    ) -> Path:
        """Persist an ``AuditResult`` snapshot to the history store.

        Args:
            audit_result: The validated audit result to record.
            hostname: Override the hostname (default: derived from
                ``audit_result.meta.url``).
            label: Optional human-readable label (e.g. "Pre-optimisation
                baseline").

        Returns:
            The path to the written snapshot file.

        The file is written as schema-compliant JSON with a ``_history_label``
        key added to the top-level dict for retrieval. Oldest entries are
        pruned if the hostname directory exceeds ``_MAX_ENTRIES``.
        """
        host = hostname or _extract_hostname(audit_result.meta.url)
        ts = audit_result.meta.timestamp_utc.replace(":", "-")
        host_dir = self._base / host
        host_dir.mkdir(parents=True, exist_ok=True)

        # Build the snapshot dict and inject history metadata.
        snapshot = audit_result.model_dump()
        snapshot["_history_label"] = label
        snapshot["_history_hostname"] = host

        path = host_dir / f"{ts}.json"
        path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

        # Prune old entries if over the cap.
        self._prune(host)

        return path

    # ------------------------------------------------------------------
    # list_entries
    # ------------------------------------------------------------------

    def list_entries(self, hostname: str) -> list[HistoryEntry]:
        """Return all snapshots for ``hostname``, sorted by time (newest first).

        Returns an empty list if the hostname has no recorded snapshots.
        """
        host_dir = self._base / hostname
        if not host_dir.is_dir():
            return []

        entries: list[HistoryEntry] = []
        for fpath in host_dir.iterdir():
            if fpath.suffix != ".json":
                continue
            try:
                entry = self._load_entry(fpath, hostname)
                if entry is not None:
                    entries.append(entry)
            except (json.JSONDecodeError, KeyError, ValueError):
                # Corrupt file — skip it silently.
                continue

        # Sort by timestamp descending (newest first). Parse ISO timestamps
        # so that values sort correctly even for non-standard dates.

        def _ts_sort_key(e: HistoryEntry) -> tuple[bool, str]:
            """Return a sort key for descending timestamp ordering.

            Tries datetime parsing first; falls back to string comparison
            if the timestamp is non-standard (e.g. zero-value placeholder).
            Returns (is_valid, sortable_string) so valid timestamps always
            sort after invalid ones.
            """
            try:
                dt = datetime.fromisoformat(e.timestamp_utc.replace("Z", "+00:00"))
                return (True, dt.isoformat())
            except (ValueError, TypeError):
                return (False, e.timestamp_utc)

        entries.sort(key=_ts_sort_key, reverse=True)
        return entries

    # ------------------------------------------------------------------
    # latest
    # ------------------------------------------------------------------

    def latest(self, hostname: str) -> HistoryEntry | None:
        """Return the most recent snapshot for ``hostname``, or ``None``."""
        entries = self.list_entries(hostname)
        return entries[0] if entries else None

    # ------------------------------------------------------------------
    # load_snapshot
    # ------------------------------------------------------------------

    def load_snapshot(self, entry: HistoryEntry) -> AuditResult:
        """Load the full ``AuditResult`` from a ``HistoryEntry``.

        Raises ``FileNotFoundError`` if the snapshot file no longer exists.
        """
        path = self._base / entry.path
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        # Strip internal history keys before validation.
        raw.pop("_history_label", None)
        raw.pop("_history_hostname", None)
        return AuditResult.model_validate(raw)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_entry(self, fpath: Path, hostname: str) -> HistoryEntry | None:
        """Read a snapshot file and return a ``HistoryEntry``."""
        with open(fpath, encoding="utf-8") as f:
            raw = json.load(f)

        meta = raw.get("meta", {})
        vitals = raw.get("vitals", {})
        images = raw.get("images", [])

        label = raw.get("_history_label")
        avg_score = (
            sum(img.get("score", 0) for img in images) / len(images)
            if images else 0.0
        )
        total_bytes = sum(img.get("bytes", 0) for img in images)

        return HistoryEntry(
            hostname=hostname,
            timestamp_utc=str(meta.get("timestamp_utc", "")),
            url=str(meta.get("url", "")),
            device=str(meta.get("device", "")),
            label=label,
            path=str(fpath.relative_to(self._base)),
            lcp_ms=float(vitals.get("lcp_ms", 0)),
            cls=float(vitals.get("cls", 0)),
            inp_ms=float(vitals.get("inp_ms", 0)),
            ttfb_ms=float(vitals.get("ttfb_ms", 0)),
            image_count=len(images),
            total_bytes=total_bytes,
            avg_score=avg_score,
        )

    def _prune(self, hostname: str) -> None:
        """Remove oldest entries beyond ``_MAX_ENTRIES``."""
        host_dir = self._base / hostname
        if not host_dir.is_dir():
            return

        files = sorted(
            [p for p in host_dir.iterdir() if p.suffix == ".json"],
            key=lambda p: p.stat().st_mtime,
        )
        while len(files) > _MAX_ENTRIES:
            oldest = files.pop(0)
            oldest.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Trend HTML generator (for ``audit history show``)
# ---------------------------------------------------------------------------

_TREND_CSS = """        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            line-height: 1.6;
            color: #333;
            background: #f5f5f5;
            padding: 20px;
        }
        .container { max-width: 1000px; margin: 0 auto; background: white; padding: 40px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }  # noqa: E501
        h1 { font-size: 1.8em; margin-bottom: 10px; color: #1a1a1a; }
        h2 { font-size: 1.3em; margin-top: 25px; margin-bottom: 10px; color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 5px; }  # noqa: E501
        .meta { background: #ecf0f1; padding: 15px; border-radius: 5px; margin-bottom: 20px; }
        .meta p { margin: 5px 0; }
        .meta strong { color: #2c3e50; }
        table { width: 100%; border-collapse: collapse; margin: 15px 0; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background: #34495e; color: white; font-weight: 600; }
        tr:hover { background: #f8f9fa; }
        .good { color: #27ae60; font-weight: bold; }
        .needs-improvement { color: #f39c12; font-weight: bold; }
        .poor { color: #e74c3c; font-weight: bold; }
        .label { display: inline-block; padding: 2px 8px; border-radius: 10px; color: white; font-size: 0.8em; background: #7f8c8d; }  # noqa: E501
        .summary-box { background: #e8f4fd; border-left: 4px solid #3498db; padding: 15px; margin: 15px 0; border-radius: 3px; }  # noqa: E501
        footer { margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; text-align: center; color: #7f8c8d; font-size: 0.9em; }"""  # noqa: E501


def _vitals_status(metric: str, value: float) -> str:
    """Return good/needs-improvement/poor based on Web Vitals thresholds."""
    thresholds: dict[str, tuple[float, float]] = {
        "lcp_ms": (2500, 4000),
        "cls": (0.1, 0.25),
        "inp_ms": (200, 500),
        "ttfb_ms": (800, 1800),
    }
    good, poor = thresholds.get(metric, (0, float("inf")))
    if value <= good:
        return "good"
    elif value <= poor:
        return "needs-improvement"
    return "poor"


def generate_trend_html(hostname: str, entries: list[HistoryEntry]) -> str:
    """Generate a trend-over-time HTML page for a store's audit history.

    Args:
        hostname: The store hostname (displayed in the page title).
        entries: Chronological history entries (newest-first is typical,
            but the method renders them oldest-first for the table).

    Returns:
        An HTML string ready to be written to a file.
    """
    # Display oldest-first in the table for chronological reading.
    table_entries = list(reversed(entries))
    latest_entry = entries[0] if entries else None

    rows = ""
    for entry in table_entries:
        lcp_cls = _vitals_status("lcp_ms", entry.lcp_ms)
        cls_cls = _vitals_status("cls", entry.cls)
        inp_cls = _vitals_status("inp_ms", entry.inp_ms)
        ttfb_cls = _vitals_status("ttfb_ms", entry.ttfb_ms)

        label_tag = f' <span class="label">{entry.label}</span>' if entry.label else ""
        ts_display = entry.timestamp_utc.replace("T", " ")[:19]

        rows += f"""                <tr>
                    <td>{ts_display}{label_tag}</td>
                    <td class="{lcp_cls}">{entry.lcp_ms:.0f}ms</td>
                    <td class="{cls_cls}">{entry.cls:.3f}</td>
                    <td class="{inp_cls}">{entry.inp_ms:.0f}ms</td>
                    <td class="{ttfb_cls}">{entry.ttfb_ms:.0f}ms</td>
                    <td>{entry.image_count}</td>
                    <td>{entry.total_bytes / 1024:.0f} KB</td>
                    <td>{entry.avg_score:.0f}</td>
                </tr>"""

    summary = ""
    if latest_entry:
        summary = f"""        <div class="summary-box">
            <strong>Latest audit:</strong> {latest_entry.timestamp_utc[:19].replace("T", " ")} &mdash;
            LCP {latest_entry.lcp_ms:.0f}ms, CLS {latest_entry.cls:.3f}, INP {latest_entry.inp_ms:.0f}ms,
            {latest_entry.image_count} images, {latest_entry.total_bytes / 1024:.0f} KB
        </div>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Audit History — {hostname}</title>
    <style>
{_TREND_CSS}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Audit History: {hostname}</h1>
        <div class="meta">
            <p><strong>Snapshots:</strong> {len(entries)}</p>
            <p><strong>Date range:</strong> {table_entries[0].timestamp_utc[:10] if table_entries else "—"}
                &ndash; {table_entries[-1].timestamp_utc[:10] if table_entries else "—"}</p>
        </div>
        {summary}
        <h2>📋 Snapshot Timeline</h2>
        <table>
            <thead>
                <tr>
                    <th>Timestamp</th>
                    <th>LCP</th>
                    <th>CLS</th>
                    <th>INP</th>
                    <th>TTFB</th>
                    <th>Images</th>
                    <th>Size</th>
                    <th>Score</th>
                </tr>
            </thead>
            <tbody>
{rows}            </tbody>
        </table>

        <footer>
            <p>Generated by shopify-image-audit — audit history report</p>
        </footer>
    </div>
</body>
</html>
"""
