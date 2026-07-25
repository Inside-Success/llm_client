"""Contract tests for durable concurrent root-budget reservations."""

from __future__ import annotations

import multiprocessing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import llm_client.io_log as io_log
from llm_client.core.errors import (
    LLMBudgetExceededError,
    LLMBudgetLeaseLostError,
    LLMBudgetReservationStoreError,
)
from llm_client.observability.budget_reservations import (
    MICRO_USD,
    acquire_budget_reservation,
    get_budget_scope_snapshot,
    normalize_budget_microusd,
    normalize_reservation_microusd,
    normalize_settled_cost_microusd,
    release_budget_reservation,
    renew_budget_reservation,
    settle_budget_reservation,
)


@pytest.fixture
def reservation_db(tmp_path: Path) -> Path:
    """Configure one disposable real SQLite observability database."""

    original_enabled = io_log._enabled
    original_path = io_log._db_path
    original_connection = io_log._db_conn
    if original_connection is not None:
        original_connection.close()
    io_log._db_conn = None
    db_path = tmp_path / "reservations.sqlite"
    io_log.configure(enabled=True, db_path=db_path)
    try:
        yield db_path
    finally:
        if io_log._db_conn is not None:
            io_log._db_conn.close()
        # The prior singleton was closed to isolate this real SQLite file; do
        # not restore a closed connection for subsequent tests.
        io_log._db_conn = None
        io_log._db_path = original_path
        io_log._enabled = original_enabled


def _insert_settled_call(scope: str, cost: float) -> None:
    db = io_log._get_db()
    db.execute(
        """INSERT INTO llm_calls (timestamp, model, cost, marginal_cost, error, trace_id)
           VALUES (?, ?, ?, ?, NULL, ?)""",
        (datetime.now(timezone.utc).isoformat(), "test-model", cost, cost, scope),
    )
    db.commit()


def _process_admit(db_path: str, barrier: multiprocessing.synchronize.Barrier, queue: multiprocessing.queues.Queue) -> None:  # type: ignore[name-defined]
    """Worker used by the cross-process transaction test."""

    import llm_client.io_log as worker_io_log
    from llm_client.core.errors import LLMBudgetExceededError
    from llm_client.observability.budget_reservations import acquire_budget_reservation

    worker_io_log.configure(enabled=True, db_path=db_path)
    barrier.wait()
    try:
        lease = acquire_budget_reservation(
            scope_trace_id="root/processes",
            call_trace_id="root/processes/child",
            max_budget=1.0,
            reservation=0.60,
        )
    except LLMBudgetExceededError:
        queue.put("rejected")
    else:
        queue.put(f"admitted:{lease.reservation_id}")


def test_parallel_reservations_fill_but_do_not_exceed_available_budget(
    reservation_db: Path,
) -> None:
    """The canonical settled-plus-active reservation example is atomic."""

    _insert_settled_call("digimon.query.abc/earlier", 0.04)
    graph = acquire_budget_reservation(
        scope_trace_id="digimon.query.abc",
        call_trace_id="digimon.query.abc/graph",
        max_budget=0.20,
        reservation=0.08,
    )
    wiki = acquire_budget_reservation(
        scope_trace_id="digimon.query.abc",
        call_trace_id="digimon.query.abc/wiki",
        max_budget=0.20,
        reservation=0.08,
    )
    with pytest.raises(LLMBudgetExceededError):
        acquire_budget_reservation(
            scope_trace_id="digimon.query.abc",
            call_trace_id="digimon.query.abc/third",
            max_budget=0.20,
            reservation=0.01,
        )

    # Terminal runtime observability precedes reservation settlement.
    _insert_settled_call("digimon.query.abc/graph", 0.06)
    settle_budget_reservation(graph, settled_cost=0.06)
    _insert_settled_call("digimon.query.abc/wiki", 0.07)
    settle_budget_reservation(wiki, settled_cost=0.07)
    snapshot = get_budget_scope_snapshot(
        scope_trace_id="digimon.query.abc", max_budget=0.20
    )
    assert snapshot.settled_microusd == 170_000
    assert snapshot.active_reserved_microusd == 0
    assert snapshot.available_microusd == 30_000


def test_two_processes_cannot_overreserve_one_scope(reservation_db: Path) -> None:
    """Separate processes sharing a SQLite file cannot both reserve $0.60/$1.00."""

    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    queue = context.Queue()
    workers = [
        context.Process(target=_process_admit, args=(str(reservation_db), barrier, queue))
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    results = [queue.get(timeout=15) for _ in workers]
    for worker in workers:
        worker.join(timeout=15)
        assert worker.exitcode == 0
    assert sum(result.startswith("admitted:") for result in results) == 1
    assert results.count("rejected") == 1


def test_scope_rejects_changed_root_budget(reservation_db: Path) -> None:
    acquire_budget_reservation(
        scope_trace_id="root/consistent",
        call_trace_id="root/consistent/a",
        max_budget=1.0,
        reservation=0.1,
    )
    with pytest.raises(ValueError, match="different normalized max_budget"):
        get_budget_scope_snapshot(scope_trace_id="root/consistent", max_budget=2.0)


def test_money_normalization_is_conservative() -> None:
    assert normalize_budget_microusd(0.0000019) == 1
    assert normalize_reservation_microusd(0.0000011) == 2
    assert normalize_settled_cost_microusd(0.0000011) == 2
    with pytest.raises(ValueError, match="normalizes to zero"):
        normalize_budget_microusd(0.0000001)


def test_disabled_store_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(io_log, "_enabled", False)
    with pytest.raises(LLMBudgetReservationStoreError, match="requires enabled"):
        get_budget_scope_snapshot(scope_trace_id="root/disabled", max_budget=1.0)


def test_release_and_settlement_are_idempotent(reservation_db: Path) -> None:
    released = acquire_budget_reservation(
        scope_trace_id="root/idempotent", call_trace_id="root/idempotent/fail",
        max_budget=1.0, reservation=0.20,
    )
    release_budget_reservation(released)
    release_budget_reservation(released)
    settled = acquire_budget_reservation(
        scope_trace_id="root/idempotent", call_trace_id="root/idempotent/success",
        max_budget=1.0, reservation=0.20,
    )
    settle_budget_reservation(settled, settled_cost=0.10)
    settle_budget_reservation(settled, settled_cost=0.10)
    snapshot = get_budget_scope_snapshot(scope_trace_id="root/idempotent", max_budget=1.0)
    assert snapshot.active_reserved_microusd == 0


def test_expired_crashed_lease_is_reclaimable(reservation_db: Path) -> None:
    started = datetime(2026, 7, 25, tzinfo=timezone.utc)
    lease = acquire_budget_reservation(
        scope_trace_id="root/expiry", call_trace_id="root/expiry/crashed",
        max_budget=1.0, reservation=1.0, now=started, lease_ttl_seconds=1,
    )
    assert lease.reserved_microusd == MICRO_USD
    replacement = acquire_budget_reservation(
        scope_trace_id="root/expiry", call_trace_id="root/expiry/replacement",
        max_budget=1.0, reservation=1.0,
        now=started + timedelta(seconds=2), lease_ttl_seconds=1,
    )
    assert replacement.reservation_id != lease.reservation_id


def test_expired_lease_cannot_be_renewed(reservation_db: Path) -> None:
    started = datetime(2026, 7, 25, tzinfo=timezone.utc)
    lease = acquire_budget_reservation(
        scope_trace_id="root/renewal", call_trace_id="root/renewal/child",
        max_budget=1.0, reservation=0.20, now=started, lease_ttl_seconds=1,
    )
    assert renew_budget_reservation(
        lease, now=started + timedelta(seconds=2), lease_ttl_seconds=1
    ) is False


def test_expired_lease_fails_at_terminal_settlement(reservation_db: Path) -> None:
    started = datetime(2026, 7, 25, tzinfo=timezone.utc)
    lease = acquire_budget_reservation(
        scope_trace_id="root/lost", call_trace_id="root/lost/child",
        max_budget=1.0, reservation=0.20, now=started, lease_ttl_seconds=1,
    )
    # A successor admission performs the authoritative expiry transition.
    acquire_budget_reservation(
        scope_trace_id="root/lost", call_trace_id="root/lost/successor",
        max_budget=1.0, reservation=0.20,
        now=started + timedelta(seconds=2), lease_ttl_seconds=1,
    )
    with pytest.raises(LLMBudgetLeaseLostError):
        settle_budget_reservation(lease, settled_cost=0.10)
