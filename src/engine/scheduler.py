"""
Scheduled re-audit (Sprint 7, TD-1).

External-cron model: a JSON config file at
``~/.shopify-image-audit/schedules.json`` lists stores to re-audit on a
schedule. The ``audit schedule run-all`` command iterates the list,
fetches fresh metrics via the PageSpeed Insights API, and records each
``AuditResult`` to ``HistoryStore``.

Scheduling itself (when to run) is delegated to the host's cron /
systemd timer / GitHub Actions schedule — this module only handles the
"what to run" half. See ``docs/runbook/scheduled_reaudit.md`` for a
crontab snippet.

File format (``schedules.json``)::

    [
        {"shop_domain": "mystore.myshopify.com",
         "url": "https://mystore.myshopify.com",
         "device": "mobile",
         "label": "Daily 09:00"},
        ...
    ]

``access_token`` is optional and only needed if the schedule also runs
Shopify inventory; for plain audits it can be omitted.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from engine._logging import get_logger
from engine._parallel import run_parallel

_log = get_logger()


# ---------------------------------------------------------------------------
# Config model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScheduleConfig:
    """One store to re-audit on a schedule."""

    shop_domain: str
    url: str
    device: str = "mobile"
    label: str | None = None
    access_token: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScheduleConfig:
        try:
            return cls(
                shop_domain=str(data["shop_domain"]),
                url=str(data["url"]),
                device=str(data.get("device", "mobile")),
                label=data.get("label"),
                access_token=data.get("access_token"),
            )
        except KeyError as exc:
            raise ValueError(f"Missing required key {exc.args[0]!r} in schedule entry") from exc

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Drop None values to keep the JSON file tidy.
        return {k: v for k, v in d.items() if v is not None}


# ---------------------------------------------------------------------------
# Run result
# ---------------------------------------------------------------------------


@dataclass
class ScheduleRunResult:
    """Outcome of one scheduled store's audit."""

    shop_domain: str
    success: bool = False
    error: str | None = None
    entry_id: str | None = None


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class ScheduleStore:
    """Filesystem-backed schedule config store.

    Persists to ``<base_dir>/schedules.json``. Each ``shop_domain`` is
    unique — adding an existing domain overwrites the previous entry.
    """

    _FILENAME = "schedules.json"

    def __init__(self, base_dir: str | Path) -> None:
        self._base = Path(base_dir)
        self._path = self._base / self._FILENAME

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> list[ScheduleConfig]:
        """Return all configured schedules. Empty list if file missing."""
        if not self._path.is_file():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            _log.warning("Schedule file %s is corrupt: %s", self._path, exc)
            return []
        if not isinstance(raw, list):
            return []
        schedules: list[ScheduleConfig] = []
        for entry in raw:
            try:
                schedules.append(ScheduleConfig.from_dict(entry))
            except ValueError as exc:
                _log.warning("Skipping bad schedule entry: %s", exc)
        return schedules

    def save(self, schedules: list[ScheduleConfig]) -> Path:
        """Write the schedule list to disk. Parent dirs are created."""
        self._base.mkdir(parents=True, exist_ok=True)
        payload = [s.to_dict() for s in schedules]
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        # schedules.json holds Shopify access tokens — keep it private on
        # POSIX. Windows lacks POSIX modes, so failure is non-fatal.
        try:
            self._path.chmod(0o600)
        except OSError as exc:
            _log.warning(
                "Could not set 0600 permissions on %s: %s — the schedule file "
                "may be readable by other users. Run `chmod 600 %s` manually.",
                self._path,
                exc,
                self._path,
            )
        return self._path

    def add(self, config: ScheduleConfig) -> list[ScheduleConfig]:
        """Add or replace a schedule (keyed by ``shop_domain``).

        Returns the updated full schedule list.
        """
        schedules = [s for s in self.load() if s.shop_domain != config.shop_domain]
        schedules.append(config)
        self.save(schedules)
        return schedules

    def remove(self, shop_domain: str) -> list[ScheduleConfig]:
        """Drop a schedule by ``shop_domain``. Returns the updated list."""
        schedules = [s for s in self.load() if s.shop_domain != shop_domain]
        self.save(schedules)
        return schedules

    def get(self, shop_domain: str) -> ScheduleConfig | None:
        for s in self.load():
            if s.shop_domain == shop_domain:
                return s
        return None


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _audit_one_schedule(
    sched: ScheduleConfig,
    *,
    history_store: Any,
    api_key: str | None,
) -> ScheduleRunResult:
    """Audit one scheduled store. Never raises — errors become ScheduleRunResult."""
    # Local import to avoid a circular dependency at module load.
    from engine.cli_helpers._dispatchers import fetch_url_as_audit

    _log.info("Schedule run: %s (%s)", sched.shop_domain, sched.url)
    try:
        audit_result = fetch_url_as_audit(
            sched.url,
            strategy=sched.device,
            api_key=api_key,
        )
    except (RuntimeError, ValueError) as exc:
        _log.warning("Schedule %s failed: %s", sched.shop_domain, exc)
        return ScheduleRunResult(
            shop_domain=sched.shop_domain,
            success=False,
            error=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 — surface any unexpected error
        _log.error("Schedule %s unexpected error: %s", sched.shop_domain, exc)
        return ScheduleRunResult(
            shop_domain=sched.shop_domain,
            success=False,
            error=f"Unexpected error: {exc}",
        )

    try:
        history_path = history_store.record(audit_result, label=sched.label)
        entries = history_store.list_entries(sched.shop_domain)
        entry_id = entries[0].id if entries else None
    except Exception as exc:  # noqa: BLE001 — history must never block
        _log.error("Schedule %s history record failed: %s", sched.shop_domain, exc)
        return ScheduleRunResult(
            shop_domain=sched.shop_domain,
            success=False,
            error=f"History record failed: {exc}",
        )

    _log.info("Schedule %s recorded: %s", sched.shop_domain, history_path)
    return ScheduleRunResult(
        shop_domain=sched.shop_domain,
        success=True,
        entry_id=entry_id,
    )


def run_all_schedules(
    schedule_store: ScheduleStore,
    *,
    history_store: Any,
    api_key: str | None = None,
    parallel: int = 1,
    stop_on_error: bool = False,
    on_done: Callable[[ScheduleConfig, ScheduleRunResult], None] | None = None,
) -> list[ScheduleRunResult]:
    """Run every configured schedule and record results to history.

    Args:
        parallel: Number of concurrent workers. ``0`` means all schedules
            concurrently (capped at ``len(schedules)``). ``1`` (default)
            is sequential.
        stop_on_error: If True, abort on the first failure; otherwise
            continue and report all failures.
        on_done: Optional callback invoked once per completed schedule
            with ``(schedule, result)``. Not called for cancelled slots.

    One store's failure does not abort the rest by default. Each result
    is recorded to ``history_store`` (a :class:`~engine.history.HistoryStore`)
    when the audit succeeds.

    Returns one :class:`ScheduleRunResult` per schedule, in config order.
    """
    schedules = schedule_store.load()
    if not schedules:
        return []

    def _cancelled(s: ScheduleConfig) -> ScheduleRunResult:
        return ScheduleRunResult(
            shop_domain=s.shop_domain,
            success=False,
            error="Cancelled due to --stop-on-error",
        )

    # Closure capture: scheduler needs history_store + api_key too.
    def _runner(sched: ScheduleConfig) -> ScheduleRunResult:
        return _audit_one_schedule(
            sched,
            history_store=history_store,
            api_key=api_key,
        )

    return run_parallel(
        schedules,
        _runner,
        parallel=parallel,
        stop_on_error=stop_on_error,
        cancelled_factory=_cancelled if stop_on_error else None,
        on_done=on_done,
    )
