"""Atomic durable reservations for concurrent root-budget admission.

This module owns the reservation ledger, not provider dispatch.  It deliberately
stores only identifiers, amounts, and lifecycle timestamps: prompts, responses,
provider payloads, and exception text never enter these tables.
"""

from __future__ import annotations

import atexit
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Callable, Literal, TypeVar

import llm_client.io_log as _io_log
from llm_client.core.errors import (
    LLMBudgetExceededError,
    LLMBudgetLeaseLostError,
    LLMBudgetReservationOverrunError,
    LLMBudgetReservationStoreError,
)

MICRO_USD = 1_000_000
DEFAULT_LEASE_TTL_SECONDS = 300
_OWNER_ID = str(uuid.uuid4())
_T = TypeVar("_T")
logger = logging.getLogger(__name__)

BudgetScopeMode = Literal["sequential", "reserved_concurrent"]


@dataclass(frozen=True)
class BudgetScopeSnapshot:
    """One normalized durable root-budget view."""

    scope_trace_id: str
    max_budget_microusd: int
    settled_microusd: int
    active_reserved_microusd: int
    available_microusd: int


@dataclass(frozen=True)
class BudgetReservationLease:
    """Opaque durable admission record owned by one process."""

    reservation_id: str
    scope_trace_id: str
    call_trace_id: str
    owner_id: str
    reserved_microusd: int


def _validate_finite_number(value: float, *, name: str, allow_zero: bool) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite numeric value, not bool")
    try:
        decimal = Decimal(str(value))
    except Exception as exc:  # Decimal has several implementation-specific errors.
        raise ValueError(f"{name} must be a finite numeric value") from exc
    if not decimal.is_finite() or decimal < 0 or (not allow_zero and decimal == 0):
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} must be a finite {qualifier} numeric value")
    return decimal


def normalize_budget_microusd(value: float) -> int:
    """Conservatively floor a positive root budget to integer micro-USD."""

    decimal = _validate_finite_number(value, name="max_budget", allow_zero=False)
    normalized = int((decimal * MICRO_USD).to_integral_value(rounding=ROUND_FLOOR))
    if normalized < 1:
        raise ValueError("max_budget is positive but normalizes to zero micro-USD")
    return normalized


def normalize_reservation_microusd(value: float) -> int:
    """Conservatively ceil a positive reservation to integer micro-USD."""

    decimal = _validate_finite_number(value, name="budget_reservation", allow_zero=False)
    normalized = int((decimal * MICRO_USD).to_integral_value(rounding=ROUND_CEILING))
    if normalized < 1:
        raise ValueError("budget_reservation is positive but normalizes to zero micro-USD")
    return normalized


def normalize_settled_cost_microusd(value: float) -> int:
    """Conservatively ceil a non-negative settled cost to integer micro-USD."""

    decimal = _validate_finite_number(value, name="settled_cost", allow_zero=True)
    return int((decimal * MICRO_USD).to_integral_value(rounding=ROUND_CEILING))


def _require_scope(scope_trace_id: str) -> str:
    if not isinstance(scope_trace_id, str) or not scope_trace_id.strip():
        raise ValueError("scope_trace_id must be a non-empty string")
    return scope_trace_id.strip()


def _require_descendant(scope_trace_id: str, call_trace_id: str) -> str:
    call_trace = _require_scope(call_trace_id)
    if call_trace != scope_trace_id and not call_trace.startswith(scope_trace_id + "/"):
        raise ValueError("call_trace_id must equal scope_trace_id or be its slash-delimited descendant")
    return call_trace


def _now(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(timezone.utc)


def _iso(now: datetime) -> str:
    return now.isoformat()


def _require_store() -> sqlite3.Connection:
    if not _io_log._logging_enabled():
        raise LLMBudgetReservationStoreError(
            "reserved_concurrent budget mode requires enabled SQLite observability"
        )
    return _io_log._get_db()


def _settled_microusd(db: sqlite3.Connection, scope_trace_id: str) -> int:
    params = (scope_trace_id, scope_trace_id + "/%")
    llm_row = db.execute(
        """SELECT COALESCE(SUM(COALESCE(marginal_cost, cost)), 0)
           FROM llm_calls
           WHERE COALESCE(marginal_cost, cost) IS NOT NULL
             AND (trace_id = ? OR trace_id LIKE ?)""",
        params,
    ).fetchone()
    embedding_row = db.execute(
        """SELECT COALESCE(SUM(cost), 0)
           FROM embeddings
           WHERE error IS NULL AND (trace_id = ? OR trace_id LIKE ?)""",
        params,
    ).fetchone()
    return normalize_settled_cost_microusd(float((llm_row or (0.0,))[0] or 0.0)) + (
        normalize_settled_cost_microusd(float((embedding_row or (0.0,))[0] or 0.0))
    )


def _expire_leases(db: sqlite3.Connection, scope_trace_id: str, now_iso: str) -> None:
    db.execute(
        """UPDATE budget_reservations
           SET status = 'expired', completed_at = ?
           WHERE scope_trace_id = ? AND status = 'active' AND expires_at <= ?""",
        (now_iso, scope_trace_id, now_iso),
    )


def _active_reserved_microusd(
    db: sqlite3.Connection,
    scope_trace_id: str,
    now_iso: str,
) -> int:
    row = db.execute(
        """SELECT COALESCE(SUM(reserved_microusd), 0)
           FROM budget_reservations
           WHERE scope_trace_id = ? AND status = 'active' AND expires_at > ?""",
        (scope_trace_id, now_iso),
    ).fetchone()
    return int((row or (0,))[0] or 0)


def _scope_budget(db: sqlite3.Connection, scope_trace_id: str) -> int | None:
    row = db.execute(
        "SELECT max_budget_microusd FROM budget_scopes WHERE scope_trace_id = ?",
        (scope_trace_id,),
    ).fetchone()
    return None if row is None else int(row[0])


def _assert_scope_budget(
    db: sqlite3.Connection,
    scope_trace_id: str,
    max_budget_microusd: int,
) -> None:
    existing = _scope_budget(db, scope_trace_id)
    if existing is not None and existing != max_budget_microusd:
        raise ValueError(
            "budget scope was previously used with a different normalized max_budget"
        )


def _transaction(operation: Callable[[sqlite3.Connection], _T]) -> _T:
    """Run one immediate SQLite transaction with the shared bounded retry policy."""

    retries = _io_log._get_db_lock_retries()
    base_delay_ms = _io_log._get_db_lock_retry_delay_ms()
    attempt = 0
    while True:
        try:
            db = _require_store()
            with _io_log._db_write_lock:
                db.execute("BEGIN IMMEDIATE")
                try:
                    result = operation(db)
                except BaseException:
                    db.rollback()
                    raise
                db.commit()
                return result
        except sqlite3.OperationalError as exc:
            try:
                if "db" in locals() and db.in_transaction:
                    db.rollback()
            except sqlite3.Error:
                pass
            if not _io_log._is_db_locked_error(exc) or attempt >= retries:
                raise LLMBudgetReservationStoreError(
                    "durable budget reservation transaction failed", original=exc
                ) from exc
            time.sleep((base_delay_ms * (attempt + 1)) / 1000.0)
            attempt += 1
        except LLMBudgetReservationStoreError:
            raise
        except sqlite3.Error as exc:
            raise LLMBudgetReservationStoreError(
                "durable budget reservation transaction failed", original=exc
            ) from exc


def get_budget_scope_snapshot(
    *,
    scope_trace_id: str,
    max_budget: float,
    now: datetime | None = None,
) -> BudgetScopeSnapshot:
    """Return settled and active durable spend without admitting a new call."""

    scope = _require_scope(scope_trace_id)
    budget = normalize_budget_microusd(max_budget)
    observed_at = _now(now)
    observed_iso = _iso(observed_at)

    def operation(db: sqlite3.Connection) -> BudgetScopeSnapshot:
        _assert_scope_budget(db, scope, budget)
        settled = _settled_microusd(db, scope)
        active = _active_reserved_microusd(db, scope, observed_iso)
        return BudgetScopeSnapshot(
            scope_trace_id=scope,
            max_budget_microusd=budget,
            settled_microusd=settled,
            active_reserved_microusd=active,
            available_microusd=max(0, budget - settled - active),
        )

    return _transaction(operation)


def raise_budget_scope_max_budget(
    *,
    scope_trace_id: str,
    expected_max_budget: float,
    new_max_budget: float,
    now: datetime | None = None,
) -> BudgetScopeSnapshot:
    """Atomically raise an existing scope cap without discarding its ledger.

    This is an explicit compare-and-set operation for resumable workloads. It
    never creates a scope or permits a decrease. Repeating the same successful
    request is idempotent, which makes recovery safe when a caller did not
    receive the first response.
    """

    scope = _require_scope(scope_trace_id)
    expected = normalize_budget_microusd(expected_max_budget)
    replacement = normalize_budget_microusd(new_max_budget)
    if replacement < expected:
        raise ValueError("new_max_budget must not decrease the expected max_budget")
    observed_at = _now(now)
    observed_iso = _iso(observed_at)

    def operation(db: sqlite3.Connection) -> BudgetScopeSnapshot:
        existing = _scope_budget(db, scope)
        if existing is None:
            raise ValueError("budget scope does not exist")
        if existing == expected:
            if replacement != expected:
                db.execute(
                    """UPDATE budget_scopes
                       SET max_budget_microusd = ?, updated_at = ?
                       WHERE scope_trace_id = ? AND max_budget_microusd = ?""",
                    (replacement, observed_iso, scope, expected),
                )
        elif existing != replacement:
            raise ValueError(
                "budget scope does not match expected max_budget or the "
                "idempotent replacement"
            )
        _expire_leases(db, scope, observed_iso)
        settled = _settled_microusd(db, scope)
        active = _active_reserved_microusd(db, scope, observed_iso)
        return BudgetScopeSnapshot(
            scope_trace_id=scope,
            max_budget_microusd=replacement,
            settled_microusd=settled,
            active_reserved_microusd=active,
            available_microusd=max(0, replacement - settled - active),
        )

    return _transaction(operation)


def acquire_budget_reservation(
    *,
    scope_trace_id: str,
    call_trace_id: str,
    max_budget: float,
    reservation: float,
    now: datetime | None = None,
    lease_ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
) -> BudgetReservationLease:
    """Atomically admit one concurrent child call under a durable root scope."""

    scope = _require_scope(scope_trace_id)
    call_trace = _require_descendant(scope, call_trace_id)
    budget = normalize_budget_microusd(max_budget)
    reserved = normalize_reservation_microusd(reservation)
    if reserved > budget:
        raise LLMBudgetExceededError("budget reservation exceeds normalized root budget")
    if isinstance(lease_ttl_seconds, bool) or lease_ttl_seconds < 1:
        raise ValueError("lease_ttl_seconds must be a positive integer")
    observed_at = _now(now)
    observed_iso = _iso(observed_at)
    expires_iso = _iso(observed_at + timedelta(seconds=lease_ttl_seconds))
    reservation_id = str(uuid.uuid4())

    def operation(db: sqlite3.Connection) -> BudgetReservationLease:
        _expire_leases(db, scope, observed_iso)
        existing = _scope_budget(db, scope)
        if existing is None:
            db.execute(
                """INSERT INTO budget_scopes
                   (scope_trace_id, max_budget_microusd, created_at, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (scope, budget, observed_iso, observed_iso),
            )
        elif existing != budget:
            raise ValueError(
                "budget scope was previously used with a different normalized max_budget"
            )
        settled = _settled_microusd(db, scope)
        active = _active_reserved_microusd(db, scope, observed_iso)
        if settled + active + reserved > budget:
            raise LLMBudgetExceededError(
                "budget reservation exceeds root scope limit: "
                f"{settled} settled + {active} active + {reserved} requested > {budget} micro-USD"
            )
        db.execute(
            """INSERT INTO budget_reservations
               (reservation_id, scope_trace_id, call_trace_id, owner_id,
                reserved_microusd, status, created_at, heartbeat_at, expires_at)
               VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)""",
            (
                reservation_id,
                scope,
                call_trace,
                _OWNER_ID,
                reserved,
                observed_iso,
                observed_iso,
                expires_iso,
            ),
        )
        return BudgetReservationLease(
            reservation_id=reservation_id,
            scope_trace_id=scope,
            call_trace_id=call_trace,
            owner_id=_OWNER_ID,
            reserved_microusd=reserved,
        )

    return _transaction(operation)


def release_budget_reservation(
    lease: BudgetReservationLease,
    *,
    now: datetime | None = None,
) -> None:
    """Idempotently release one active lease after a failed call or cancellation."""

    completed_iso = _iso(_now(now))

    def operation(db: sqlite3.Connection) -> None:
        db.execute(
            """UPDATE budget_reservations
               SET status = 'released_error', completed_at = ?
               WHERE reservation_id = ? AND owner_id = ? AND status = 'active'""",
            (completed_iso, lease.reservation_id, lease.owner_id),
        )

    _transaction(operation)


def settle_budget_reservation(
    lease: BudgetReservationLease,
    *,
    settled_cost: float,
    now: datetime | None = None,
) -> None:
    """Idempotently settle a lease and fail loudly after recording an overrun."""

    settled = normalize_settled_cost_microusd(settled_cost)
    completed_iso = _iso(_now(now))

    def operation(db: sqlite3.Connection) -> bool:
        row = db.execute(
            """SELECT reserved_microusd, status, settled_cost_microusd
               FROM budget_reservations WHERE reservation_id = ? AND owner_id = ?""",
            (lease.reservation_id, lease.owner_id),
        ).fetchone()
        if row is None:
            raise LLMBudgetReservationStoreError("durable budget reservation was not found")
        reserved, status = int(row[0]), str(row[1])
        observed_settled = settled
        if status == "active":
            db.execute(
                """UPDATE budget_reservations
                   SET status = 'settled', completed_at = ?, settled_cost_microusd = ?
                   WHERE reservation_id = ? AND owner_id = ? AND status = 'active'""",
                (completed_iso, observed_settled, lease.reservation_id, lease.owner_id),
            )
        elif status == "expired":
            raise LLMBudgetLeaseLostError(
                "durable budget reservation expired before call completion"
            )
        elif status != "settled":
            return False
        else:
            observed_settled = int(row[2] or 0)
        return observed_settled > reserved

    overrun = _transaction(operation)
    if overrun:
        raise LLMBudgetReservationOverrunError(
            "completed call cost exceeded its admitted budget reservation"
        )


def renew_budget_reservation(
    lease: BudgetReservationLease,
    *,
    now: datetime | None = None,
    lease_ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
) -> bool:
    """Refresh one owned active lease; return False if ownership was lost."""

    if isinstance(lease_ttl_seconds, bool) or lease_ttl_seconds < 1:
        raise ValueError("lease_ttl_seconds must be a positive integer")
    observed_at = _now(now)
    observed_iso = _iso(observed_at)
    expires_iso = _iso(observed_at + timedelta(seconds=lease_ttl_seconds))

    def operation(db: sqlite3.Connection) -> bool:
        cursor = db.execute(
            """UPDATE budget_reservations
               SET heartbeat_at = ?, expires_at = ?
               WHERE reservation_id = ? AND owner_id = ?
                 AND status = 'active' AND expires_at > ?""",
            (
                observed_iso,
                expires_iso,
                lease.reservation_id,
                lease.owner_id,
                observed_iso,
            ),
        )
        return cursor.rowcount == 1

    return _transaction(operation)


class _BudgetLeaseKeeper:
    """One daemon renewal loop for every durable lease owned by this process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._leases: dict[str, BudgetReservationLease] = {}
        self._lost: set[str] = set()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def track(self, lease: BudgetReservationLease) -> None:
        with self._lock:
            self._leases[lease.reservation_id] = lease
            self._lost.discard(lease.reservation_id)
            if self._thread is None or not self._thread.is_alive():
                self._stop.clear()
                self._thread = threading.Thread(
                    target=self._run,
                    name="llm-client-budget-lease-keeper",
                    daemon=True,
                )
                self._thread.start()
        self._wake.set()

    def untrack(self, lease: BudgetReservationLease) -> None:
        with self._lock:
            self._leases.pop(lease.reservation_id, None)
            self._lost.discard(lease.reservation_id)
        self._wake.set()

    def lost(self, lease: BudgetReservationLease) -> bool:
        with self._lock:
            return lease.reservation_id in self._lost

    def renew_once(self, *, now: datetime | None = None) -> None:
        """Renew all local leases once; exposed for deterministic tests."""

        with self._lock:
            leases = tuple(self._leases.values())
        for lease in leases:
            try:
                renewed = renew_budget_reservation(lease, now=now)
            except Exception:
                logger.exception("durable budget lease renewal failed: %s", lease.reservation_id)
                renewed = False
            if not renewed:
                with self._lock:
                    self._lost.add(lease.reservation_id)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(timeout=30)
            self._wake.clear()
            if self._stop.is_set():
                return
            self.renew_once()

    def shutdown(self) -> None:
        self._stop.set()
        self._wake.set()


_lease_keeper = _BudgetLeaseKeeper()
atexit.register(_lease_keeper.shutdown)


def track_budget_reservation(lease: BudgetReservationLease) -> None:
    """Begin process-wide heartbeat renewal for one admitted durable lease."""

    _lease_keeper.track(lease)


def release_tracked_budget_reservation(lease: BudgetReservationLease) -> None:
    """Release a durable lease and remove it from process renewal."""

    try:
        release_budget_reservation(lease)
    finally:
        _lease_keeper.untrack(lease)


def settle_tracked_budget_reservation(
    lease: BudgetReservationLease,
    *,
    settled_cost: float,
) -> None:
    """Settle a tracked lease or expose lost custody at the terminal boundary."""

    try:
        if _lease_keeper.lost(lease):
            raise LLMBudgetLeaseLostError(
                "durable budget reservation lease was lost before call completion"
            )
        settle_budget_reservation(lease, settled_cost=settled_cost)
    finally:
        _lease_keeper.untrack(lease)
