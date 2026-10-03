"""Structured resume compilation and escaped, provider-independent rendering."""

from html import escape
from typing import Literal, Protocol

from pydantic import Field

from career.schemas import Claim, Schema


class ResumeBullet(Schema):
    text: str = Field(min_length=1)
    evidence_ids: list[str] = []
    profile_fact_ids: list[str] = []
    claims: list[Claim] = Field(min_length=1)


class ResumeSection(Schema):
    title: str = Field(min_length=1)
    kind: Literal["SUMMARY", "EXPERIENCE", "PROJECT", "EDUCATION", "SKILLS"]
    bullets: list[ResumeBullet] = Field(min_length=1)


class ResumeContent(Schema):
    sections: list[ResumeSection] = Field(min_length=1)


class ResumeRenderer(Protocol):
    media_type: str

    def render(self, content: ResumeContent) -> str | bytes: ...


class MarkdownRenderer:
    media_type = "text/markdown"

    def render(self, content: ResumeContent) -> str:
        return "\n\n".join(
            "## " + s.title + "\n" + "\n".join("- " + b.text for b in s.bullets) for s in content.sections
        )


class HTMLRenderer:
    media_type = "text/html"

    def render(self, content: ResumeContent) -> str:
        sections = "".join(
            "<section><h2>"
            + escape(s.title)
            + "</h2><ul>"
            + "".join("<li>" + escape(b.text) + "</li>" for b in s.bullets)
            + "</ul></section>"
            for s in content.sections
        )
        return (
            '<!doctype html><html lang="ko"><meta charset="utf-8"><title>이력서</title><style>body{max-width:800px;margin:40px auto;padding:24px;font:15px/1.8 sans-serif;color:#252733}h2{font-size:19px;border-bottom:1px solid #ddd}li{margin:10px 0}@media print{body{margin:0}}</style><body>'
            + sections
            + "</body></html>"
        )


def structured_document(content: ResumeContent, allowed: set[str], profile=None) -> dict:
    profile = profile or {}
    profile_ids = {item["id"] for item in profile.values() if item.get("fact_type") == "profile"}
    claims = []
    for section in content.sections:
        for bullet in section.bullets:
            if not set(bullet.evidence_ids) <= allowed:
                raise ValueError("이력서 항목이 선택하지 않은 근거를 참조합니다.")
            if not (bullet.evidence_ids or bullet.profile_fact_ids) or not set(bullet.profile_fact_ids) <= profile_ids:
                raise ValueError("이력서 항목에 현재 확인된 사실 또는 경험 근거를 연결해 주세요.")
            for claim in bullet.claims:
                if claim.text not in bullet.text or not set(claim.evidence_ids) <= set(bullet.evidence_ids):
                    raise ValueError("각 항목의 문장과 주장 근거를 일치시켜 주세요.")
                if not set(claim.profile_fact_ids) <= set(bullet.profile_fact_ids):
                    raise ValueError("항목과 확인된 프로필 사실의 출처를 일치시켜 주세요.")
                claims.append(claim.model_dump())
    return {"text": MarkdownRenderer().render(content), "claims": claims, **content.model_dump()}


def legacy_sections(document: dict) -> dict:
    # Preserve user text verbatim; a single section provides a lossless editable model.
    content = ResumeContent(
        sections=[
            ResumeSection(
                title="경력·프로젝트",
                kind="EXPERIENCE",
                bullets=[
                    ResumeBullet(
                        text=document["text"],
                        evidence_ids=list(
                            dict.fromkeys(e for c in document["claims"] for e in c["evidence_ids"])
                        ),
                        profile_fact_ids=list(dict.fromkeys(f for c in document["claims"] for f in c.get("profile_fact_ids", []))),
                        claims=document["claims"],
                    )
                ],
            )
        ]
    )
    return content.model_dump()
