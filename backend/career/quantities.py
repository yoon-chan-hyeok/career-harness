"""Conservative numeric parsing for document comparison, never fact generation."""

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext

_NUMBER = r"[+-]?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_UNIT = r"%p|퍼센트포인트|percentage\s+points?|pp|%|퍼센트|percent|milliseconds?|ms|seconds?|secs?|초|minutes?|mins?|분|hours?|hrs?|시간|points?|scores?|점|people|persons?|items?|cases?|times|배|명|건|개월|개|회|일|년|KiB|MiB|GiB|TiB|KB|MB|GB|TB|B"
_QUANTITY = re.compile(r"(?<![\dA-Za-z_])(" + _NUMBER + r")\s*(천|만|억)?\s*(" + _UNIT + r")?", re.I)
_DATES = re.compile(
    r"(?<!\d)(?:19|20|21)\d{2}(?:[-/.]\d{1,2}){1,2}(?!\d)|(?:19|20|21)\d{2}\s*년(?:\s*\d{1,2}\s*월)?(?:\s*\d{1,2}\s*일)?"
)
_VERSION = re.compile(
    r"(?:\b(?:python|java|node(?:\.js)?|gpt|llama|qwen|pytorch|tensorflow|react|next(?:\.js)?|cuda|postgresql)[\w.\-]*|\b(?:version|ver|v)|버전)\s*[-.:]?\s*$",
    re.I,
)
_SCALE = {None: Decimal(1), "천": Decimal(1000), "만": Decimal(10000), "억": Decimal(100000000)}


def numeric_token(token: str) -> str:
    """Preserve percent/multiple distinction while normalizing literal formatting."""
    token = unicodedata.normalize("NFKC", token)
    suffix = "%" if token.endswith("%") else "배" if token.endswith("배") else ""
    raw = token[: -len(suffix)] if suffix else token
    if "," in raw and not re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", raw):
        return token
    try:
        number = format(Decimal(raw.replace(",", "")), "f")
        if "." in number:
            number = number.rstrip("0").rstrip(".")
        return ("0" if number == "-0" else number) + suffix
    except InvalidOperation:
        return token


def numeric_tokens(text: str) -> set[str]:
    text = re.sub(r"(?<=\d)\s+(?=[%배])", "", text)
    return {numeric_token(token) for token in re.findall(r"\d+(?:[.,]\d+)*(?:%|배)?", text)}


def _multiply(value: Decimal, factor: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = max(28, len(value.as_tuple().digits) + len(factor.as_tuple().digits) + 8)
        return value * factor


def unit_value(value: Decimal, unit: str) -> tuple[Decimal, str]:
    key = unit.casefold().strip()
    key = {
        "point": "점",
        "points": "점",
        "score": "점",
        "scores": "점",
        "people": "명",
        "person": "명",
        "persons": "명",
        "item": "개",
        "items": "개",
        "case": "건",
        "cases": "건",
        "times": "회",
    }.get(key, key)
    if key in {"%", "퍼센트", "percent"}:
        return value, "%"
    if key in {"%p", "pp", "퍼센트포인트", "percentage point", "percentage points"}:
        return value, "pp"
    for units, factor in (
        ({"ms", "millisecond", "milliseconds"}, "0.001"),
        ({"초", "second", "seconds", "sec", "secs"}, "1"),
        ({"분", "minute", "minutes", "min", "mins"}, "60"),
        ({"시간", "hour", "hours", "hr", "hrs"}, "3600"),
    ):
        if key in units:
            return _multiply(value, Decimal(factor)), "seconds"
    for prefix, factor in {
        "b": 1,
        "kb": 1000,
        "mb": 1000000,
        "gb": 1000000000,
        "tb": 1000000000000,
        "kib": 1024,
        "mib": 1048576,
        "gib": 1073741824,
        "tib": 1099511627776,
    }.items():
        if key == prefix:
            return _multiply(value, Decimal(factor)), "bytes"
    return value, key


@dataclass(frozen=True)
class Quantity:
    value: Decimal
    unit: str
    start: int
    end: int
    text: str

    @property
    def key(self) -> tuple[Decimal, str]:
        return unit_value(self.value, self.unit)


def quantities(text: str, *, ignore_identifiers=False) -> list[Quantity]:
    # NFKC preserves normal Korean/ASCII offsets used by the stored Claim quote.
    normalized = unicodedata.normalize("NFKC", text)
    result = []
    dates = list(_DATES.finditer(normalized)) if ignore_identifiers else []
    for match in _QUANTITY.finditer(normalized):
        if ignore_identifiers and (
            any(date.start() <= match.start() < date.end() for date in dates)
            or (
                (not match[3] or match[3].casefold() == "b")
                and _VERSION.search(normalized[max(0, match.start() - 40) : match.start()])
            )
        ):
            continue
        unit = match[3] or ""
        if (
            not unit
            and match.end() < len(normalized)
            and normalized[match.end()].isascii()
            and normalized[match.end()].isalpha()
        ):
            continue
        try:
            value = _multiply(Decimal(match[1].replace(",", "")), _SCALE[match[2]])
        except InvalidOperation:
            continue
        result.append(Quantity(value, unit, match.start(), match.end(), match[0].strip()))
    return result


def canonical_quantity(value: str, unit: str) -> Quantity | None:
    # Complex ranges/ratios require explicit interpretation; do not select one number.
    parsed = quantities(value)
    if len(parsed) != 1:
        return None
    item = parsed[0]
    return Quantity(item.value, item.unit or unit, item.start, item.end, item.text)


def quantity_role(text: str, item: Quantity) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    before = normalized[max(0, item.start - 24) : item.start]
    after = normalized[item.end : item.end + 12].lstrip()
    if re.match(r"에서|→|->|to\b", after, re.I):
        return "baseline"
    markers = list(re.finditer(r"기존|이전|기준(?:값)?|baseline|before|\bfrom\b", before, re.I))
    if markers:
        between = before[markers[-1].end() :]
        if not re.search(r"\d|개선|최종|현재|보다|결과|변경\s*후|after", between, re.I):
            return "baseline"
    return "value"
