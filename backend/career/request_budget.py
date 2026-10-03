"""A single deadline shared by every stage and copied into review workers."""

from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from dataclasses import replace
from threading import Event, Thread
from time import monotonic

from career.provider_policy import BudgetExceeded, StagePolicy

request_deadline: ContextVar[float | None] = ContextVar("career_request_deadline", default=None)


@contextmanager
def deadline_scope(seconds: float = 100):
    parent = request_deadline.get()
    token = request_deadline.set(min(parent, monotonic() + seconds) if parent else monotonic() + seconds)
    try:
        yield
    finally:
        request_deadline.reset(token)


def check_deadline() -> None:
    deadline = request_deadline.get()
    if deadline is not None and monotonic() >= deadline:
        raise BudgetExceeded("REQUEST_DEADLINE_EXCEEDED")


def bounded_policy(policy: StagePolicy) -> StagePolicy:
    """SDK connect/read/write/pool timeouts are each bounded by the remaining time."""
    check_deadline()
    deadline = request_deadline.get()
    if deadline is None:
        return policy
    return replace(policy, timeout_seconds=min(policy.timeout_seconds, max(0.001, deadline - monotonic())))


def call_with_deadline(call, policy: StagePolicy):
    """Enforce wall time as well as the SDK's per-socket timeouts.

    Only the SDK/HTTP call runs in the daemon thread. Final validation, database
    access, traces and workflow advancement remain on the requesting thread.
    A late remote response is discarded; the request is conservatively charged.
    This is never a background workflow or a promise to cancel remote billing.
    """
    timeout = bounded_policy(policy).timeout_seconds
    finished = Event()
    result = []
    errors = []

    def invoke():
        try:
            result.append(call())
        except Exception as error:
            errors.append(error)
        finally:
            finished.set()

    Thread(target=copy_context().run, args=(invoke,), daemon=True, name="career-http").start()
    if not finished.wait(timeout):
        deadline = request_deadline.get()
        if deadline is not None and monotonic() >= deadline:
            raise BudgetExceeded("REQUEST_DEADLINE_EXCEEDED")
        raise BudgetExceeded("LATENCY_BUDGET_EXCEEDED")
    check_deadline()
    if errors:
        raise errors[0]
    return result[0]
