"""Durable per-user limits, independent of a provider's balance or billing.

Reserve once before the business transaction, then draw from a thread-safe
envelope without DB access during HTTP calls. Settlement runs only after the
request session releases its connection. This works with SQLite's single writer
and a one-connection serverless pool. Crashes keep their worst-case reservation.
"""

import math
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any

from sqlalchemy import event, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from career.cache_metrics import summarize_cache
from career.db import now, uid
from career.models import AIUsageBucket, AIUsageReservation, AIUsageSettings, PromptRun
from career.provider_policy import (
    BudgetExceeded,
    StagePolicy,
    estimated_cost,
    request_cost_ceiling,
    token_totals,
)
from career.request_budget import check_deadline, deadline_scope
from career.service_access import (
    SHARED_BUDGET_USER,
    ceiling,
    effective_limits,
    require_member,
    shared_service,
)

DEFAULT_LIMITS = {
    "daily_calls": 100, "monthly_calls": 1000,
    "daily_tokens": 200000, "monthly_tokens": 2000000,
    "daily_cost_usd": None, "monthly_cost_usd": None,
}
# Capacity, not predicted activity. Unstarted calls are returned at settlement.
ACTION_CALLS = {
    "conversation": 5, "commands": 5, "analyze": 2,
    "research": 2, "resume": 2, "review": 3,
    "evidence-map": 2, "strategy": 4, "question-brief": 2,
    "provider_check": 1, "revise": 1,
}
CAPACITY_TOKENS_PER_CALL = 49152


def validate_limits(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - DEFAULT_LIMITS.keys():
        raise ValueError("사용량 한도 항목을 확인해 주세요.")
    result = {**DEFAULT_LIMITS, **value}
    for name, item in result.items():
        if name.endswith("cost_usd"):
            if item is None:
                continue
            if isinstance(item, bool) or not isinstance(item, int | float) or not math.isfinite(item) or not 0 <= item <= 1000:
                raise ValueError("비용 한도는 0~1000 사이 숫자 또는 미설정이어야 합니다.")
        elif isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= 100000000:
            raise ValueError("호출·토큰 한도는 0~100000000 사이 정수여야 합니다.")
    return result


def _settings(db: Session, user: str, lock=False):
    if lock:
        dialect = db.get_bind().dialect.name
        insert = sqlite_insert if dialect == "sqlite" else pg_insert
        db.execute(insert(AIUsageSettings).values(id=uid(), user_id=user, created_at=now(), data=DEFAULT_LIMITS)
                   .on_conflict_do_nothing(index_elements=["user_id"]))
    query = select(AIUsageSettings).where(AIUsageSettings.user_id == user)
    return db.scalar(query.with_for_update() if lock else query)


def configure_usage(db: Session, user: str, value: dict[str, Any]) -> dict[str, Any]:
    limits = validate_limits(value)
    if shared_service() and user != SHARED_BUDGET_USER:
        _settings(db, SHARED_BUDGET_USER, lock=True)
        effective = effective_limits(db, user, limits)
        if any(effective[key] != limits[key] for key in value):
            raise ValueError("운영자가 정한 한도를 초과할 수 없습니다. 더 낮은 개인 한도만 설정할 수 있습니다.")
        limits = effective
    row = _settings(db, user, lock=True)
    assert row is not None
    row.data = limits
    db.flush()
    return {"limits": limits, "defaults": effective_limits(db, user, DEFAULT_LIMITS),
            "managed": shared_service() and user != SHARED_BUDGET_USER,
            "notice": "운영자 상한과 공용 한도를 함께 적용합니다." if shared_service() else "앱 실행 한도입니다. 제공자 잔액·과금 제한은 별도로 확인하세요."}


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _periods(instant: datetime | None = None):
    instant = _utc(instant if instant is not None else now())
    return ["D:" + instant.strftime("%Y-%m-%d"), "M:" + instant.strftime("%Y-%m")]


def _empty():
    return {"calls": 0, "tokens": 0, "cost_microusd": 0, "known_cost_microusd": 0, "unknown_cost_calls": 0,
            "reserved_calls": 0, "reserved_tokens": 0, "reserved_cost_microusd": 0}


def _ledger_data(value: dict[str, Any]) -> dict[str, Any]:
    data = {**_empty(), **value}
    if "known_cost_microusd" not in value:
        # Old mixed reservations cannot reconstruct the observed cost portion.
        data["known_cost_microusd"] = data["cost_microusd"] if not (
            data["unknown_cost_calls"] or data["reserved_calls"]
        ) or data["cost_microusd"] == 0 else None
    return data


def _buckets(db: Session, user: str, periods: list[str], create=False):
    values = []
    for period in periods:
        row = db.scalar(select(AIUsageBucket).where(AIUsageBucket.user_id == user, AIUsageBucket.period == period))
        if row is None and create:
            row = AIUsageBucket(user_id=user, period=period, data=_empty())
            db.add(row)
            db.flush()
        values.append(row)
    return values


def usage_status(db: Session, user: str) -> dict[str, Any]:
    setting = _settings(db, user)
    personal = validate_limits(setting.data if setting else {})
    limits = effective_limits(db, user, personal)
    result: dict[str, Any] = {
        "limits": limits, "defaults": effective_limits(db, user, DEFAULT_LIMITS), "timezone": "UTC",
        "managed": shared_service() and user != SHARED_BUDGET_USER,
        "operator_ceiling": ceiling(db, user) if shared_service() and user != SHARED_BUDGET_USER else None,
        "account_balance_known": False,
        "notice": "호출 전 최대 사용량을 예약합니다. 실패·사용량 미확인 호출은 보수적으로 차감하고, 중단된 실행의 예약은 유지합니다. 제공자 잔액·청구를 보장하지 않습니다.",
    }
    instant = _utc(now())
    periods = _periods(instant)
    day_start = instant.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    month_start = instant.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_end = month_start.replace(year=month_start.year + 1, month=1) if month_start.month == 12 else (
        month_start.replace(month=month_start.month + 1)
    )
    traces = list(db.execute(select(PromptRun.created_at, PromptRun.data).where(
        PromptRun.user_id == user, PromptRun.created_at >= month_start, PromptRun.created_at < month_end,
        PromptRun.provider.in_(["OpenAI", "HuggingFace", "Groq"]),
    )))
    for prefix, period, row in zip(("daily", "monthly"), periods, _buckets(db, user, periods), strict=True):
        data = _ledger_data(row.data if row else {})
        cost_limit = limits[prefix + "_cost_usd"]
        result[prefix] = {
            "period": period[2:], "calls": data["calls"], "tokens": data["tokens"],
            "estimated_cost_usd": None if data["unknown_cost_calls"] or data["reserved_calls"] else data["cost_microusd"] / 1000000,
            "known_estimated_cost_usd": None if data["known_cost_microusd"] is None else data["known_cost_microusd"] / 1000000,
            "unknown_cost_calls": data["unknown_cost_calls"],
            "reserved_calls": data["reserved_calls"], "reserved_tokens": data["reserved_tokens"],
            "remaining_calls": max(0, limits[prefix + "_calls"] - data["calls"]),
            "remaining_tokens": max(0, limits[prefix + "_tokens"] - data["tokens"]),
            "remaining_cost_usd": None if cost_limit is None or data["unknown_cost_calls"] else max(0, cost_limit - data["cost_microusd"] / 1000000),
            "basis": "APP_RESERVATIONS_AND_PROVIDER_USAGE_ESTIMATES",
            "cache": summarize_cache(data for created, data in traces
                                     if prefix == "monthly" or day_start <= _utc(created) < day_end),
        }
    return result


@dataclass
class CallTicket:
    tokens: int
    cost: int | None
    charged_tokens: int | None = None
    charged_cost: int | None = None
    cost_observed: bool = False


@dataclass
class UsageEnvelope:
    bind: Any
    user: str
    reservation_id: str
    calls: int
    tokens: int
    cost: int | None
    cost_limited: bool
    tickets: list[CallTicket] = field(default_factory=list)
    lock: Any = field(default_factory=Lock)

    def draw(self, policy: StagePolicy, input_tokens: int, uses_tools=False) -> CallTicket:
        tokens = input_tokens + policy.max_output_tokens
        # All input is priced at the highest configured input/cache rate in the
        # provider estimate below; no unspecified price is treated as zero.
        cost = request_cost_ceiling(policy, input_tokens, uses_tools)
        cost_units = math.ceil(cost * 1000000) if cost is not None else None
        with self.lock:
            if self.cost_limited and cost_units is None:
                raise BudgetExceeded("COST_BUDGET_UNVERIFIABLE")
            if len(self.tickets) >= self.calls or sum(t.charged_tokens if t.charged_tokens is not None else t.tokens for t in self.tickets) + tokens > self.tokens:
                raise BudgetExceeded("USAGE_LIMIT_EXCEEDED")
            if self.cost_limited and sum(t.charged_cost if t.charged_cost is not None else (t.cost or 0) for t in self.tickets) + (cost_units or 0) > (self.cost or 0):
                raise BudgetExceeded("USAGE_LIMIT_EXCEEDED")
            ticket = CallTicket(tokens, cost_units)
            self.tickets.append(ticket)
            return ticket

    def settle_call(self, ticket: CallTicket, model: str, usage: dict | None, tool_calls: int | None = 0):
        counts = token_totals(usage)
        cost = estimated_cost(model, usage, tool_calls)
        with self.lock:
            ticket.charged_tokens = counts[0] + counts[1] if counts else ticket.tokens
            ticket.charged_cost = math.ceil(cost * 1000000) if cost is not None else ticket.cost
            ticket.cost_observed = cost is not None


usage_envelope: ContextVar[UsageEnvelope | None] = ContextVar("career_usage_envelope", default=None)


def _reserve(db: Session, user: str, action: str) -> UsageEnvelope:
    # The caller MUST release its business connection before this transaction.
    bind = db.get_bind()
    with Session(bind) as ledger, ledger.begin():
        scopes = [user]
        if shared_service():
            _settings(ledger, SHARED_BUDGET_USER, lock=True)
            require_member(ledger, user)
            scopes.insert(0, SHARED_BUDGET_USER)
        setting = _settings(ledger, user, lock=True)
        assert setting is not None
        limits = effective_limits(ledger, user, validate_limits(setting.data))
        periods = _periods()
        constraints = []
        for scope in scopes:
            scope_setting = _settings(ledger, scope)
            assert scope_setting is not None
            cap = limits if scope == user else validate_limits(scope_setting.data)
            constraints.append((scope, _buckets(ledger, scope, periods, create=True), cap))
        calls = ACTION_CALLS.get(action, 2)
        tokens = calls * CAPACITY_TOKENS_PER_CALL
        cost_available = []
        for prefix, bucket, cap in ((prefix, bucket, cap) for _, buckets, cap in constraints
                                   for prefix, bucket in zip(("daily", "monthly"), buckets, strict=True)):
            assert bucket is not None
            calls = min(calls, max(0, cap[prefix + "_calls"] - bucket.data["calls"]))
            tokens = min(tokens, max(0, cap[prefix + "_tokens"] - bucket.data["tokens"]))
            limit = cap[prefix + "_cost_usd"]
            if limit is not None:
                if bucket.data["unknown_cost_calls"]:
                    raise BudgetExceeded("COST_BUDGET_UNVERIFIABLE")
                cost_available.append(max(0, math.floor(limit * 1000000) - bucket.data["cost_microusd"]))
        if calls == 0 or tokens == 0:
            raise BudgetExceeded("USAGE_LIMIT_EXCEEDED")
        cost = min(cost_available) if cost_available else None
        for bucket in (bucket for _, buckets, _ in constraints for bucket in buckets):
            assert bucket is not None
            data = _ledger_data(bucket.data)
            for name, amount in (("calls", calls), ("tokens", tokens), ("cost_microusd", cost or 0),
                                 ("reserved_calls", calls), ("reserved_tokens", tokens), ("reserved_cost_microusd", cost or 0)):
                data[name] += amount
            bucket.data = data
        reservation = AIUsageReservation(user_id=user, data={"periods": periods, "action": action, "scopes": scopes,
            "calls": calls, "tokens": tokens, "cost_microusd": cost, "cost_limited": bool(cost_available)})
        ledger.add(reservation)
        ledger.flush()
        ident = reservation.id
    return UsageEnvelope(bind, user, ident, calls, tokens, cost, bool(cost_available))


def _settle(envelope: UsageEnvelope):
    with Session(envelope.bind) as ledger, ledger.begin():
        # Always take the global lock first, including reservations made before a mode change.
        _settings(ledger, SHARED_BUDGET_USER, lock=True)
        _settings(ledger, envelope.user, lock=True)
        reservation = ledger.get(AIUsageReservation, envelope.reservation_id)
        if reservation is None or reservation.status != "RESERVED":
            return
        calls = len(envelope.tickets)
        tokens = sum(t.charged_tokens if t.charged_tokens is not None else t.tokens for t in envelope.tickets)
        cost = sum(t.charged_cost if t.charged_cost is not None else (t.cost or 0) for t in envelope.tickets)
        unknown = sum(not t.cost_observed for t in envelope.tickets)
        known_cost = sum(t.charged_cost or 0 for t in envelope.tickets if t.cost_observed)
        for bucket in (bucket for scope in reservation.data.get("scopes", [envelope.user])
                       for bucket in _buckets(ledger, scope, reservation.data["periods"])):
            assert bucket is not None
            data = _ledger_data(bucket.data)
            for name, before, after in (("calls", envelope.calls, calls), ("tokens", envelope.tokens, tokens),
                                       ("cost_microusd", envelope.cost or 0, cost)):
                data[name] += after - before
            data["unknown_cost_calls"] += unknown
            if data["known_cost_microusd"] is not None:
                data["known_cost_microusd"] += known_cost
            data["reserved_calls"] -= envelope.calls
            data["reserved_tokens"] -= envelope.tokens
            data["reserved_cost_microusd"] -= envelope.cost or 0
            bucket.data = data
        reservation.status = "SETTLED"
        reservation.data = {**reservation.data, "charged_calls": calls, "charged_tokens": tokens,
                            "charged_cost_microusd": cost, "known_cost_microusd": known_cost,
                            "unknown_cost_calls": unknown}


def _settle_safely(envelope: UsageEnvelope):
    try:
        _settle(envelope)
    except Exception:
        # The independent transaction rolls back; a conservative reservation
        # remains durable. Settlement must not overwrite an operation failure
        # or prevent request ContextVars from being released.
        pass


@event.listens_for(Session, "after_transaction_end")
def _after_transaction_end(db, transaction):
    if transaction.parent is not None:
        return
    for envelope in db.info.pop("career_usage_pending", []):
        _settle_safely(envelope)


@contextmanager
def request_budget_scope(db: Session, user: str, action="provider_check"):
    with deadline_scope(100):
        check_deadline()
        active = usage_envelope.get()
        if active is not None:
            if active.user != user or active.bind is not db.get_bind():
                raise ValueError("다른 사용자의 AI 실행 한도를 함께 사용할 수 없습니다.")
            yield active
            return
        if db.in_transaction():
            raise ValueError("AI 실행 예약 전에 저장 작업을 마쳐야 합니다. 현재 요청을 다시 확인해 주세요.")
        envelope = _reserve(db, user, action)
        token = usage_envelope.set(envelope)
        try:
            check_deadline()
            yield envelope
        finally:
            usage_envelope.reset(token)
            if db.in_transaction():
                db.info.setdefault("career_usage_pending", []).append(envelope)
            else:
                _settle_safely(envelope)
