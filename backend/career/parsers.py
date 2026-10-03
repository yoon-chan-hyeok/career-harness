"""Private source parsers, selected by format and optionally source category."""

import json
from collections.abc import Callable
from typing import Any

Parser = Callable[[str, str], list[Any]]


class ParserRegistry:
    def __init__(self):
        self.parsers: dict[tuple[str, str], Parser] = {}

    def register(self, suffix: str, parser: Parser, category="*"):
        self.parsers[(suffix.lower(), category)] = parser

    def parse(self, suffix: str, category: str, content: str):
        parser = self.parsers.get((suffix.lower(), category)) or self.parsers.get((suffix.lower(), "*"))
        if parser is None:
            raise ValueError("지원하지 않는 원자료 형식입니다.")
        return parser(content, category)


def parse_json(content: str, category: str):
    data = json.loads(content)
    return data if isinstance(data, list) else [data]


def parse_jsonl(content: str, category: str):
    return [json.loads(line) for line in content.splitlines() if line.strip()]


def parse_text(content: str, category: str):
    return [{"type": "EXPRESSION" if category == "final_applications" else "EVIDENCE", "statement": content}]


registry = ParserRegistry()
for suffix, parser in [
    (".json", parse_json),
    (".jsonl", parse_jsonl),
    (".txt", parse_text),
    (".md", parse_text),
]:
    registry.register(suffix, parser)
