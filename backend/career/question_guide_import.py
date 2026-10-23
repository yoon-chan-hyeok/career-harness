"""Offline, versioned guide intake. Imports cannot grant themselves publication rights."""

import json
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, JsonValue, field_validator, model_validator

from career.question_contracts import Contract, LengthPolicy, Positive, Text, fingerprint
from career.writing_plans import family

IMPORT_VERSION = "question-guide-import-v1"
MAX_IMPORT_BYTES = 2_000_000
MAX_RECORD_BYTES = 4_000_000


class Scope(Contract):
    company: Text
    role: Text
    question_id: Text


class Allocation(Contract):
    content: Text
    approximate_characters: Positive


class GuideInput(Contract):
    """Curator input schema. Original JSON is retained separately, including optional source data."""

    guide_id: Annotated[str, Field(min_length=1, max_length=180)]
    version: Positive
    source_ref: Text
    source_scope: Scope
    question: Text
    length: LengthPolicy
    required_demands: tuple[Text, ...] = ()
    question_intent: Text
    allocation: Annotated[tuple[Allocation, ...], Field(min_length=1, max_length=12)]

    @model_validator(mode="after")
    def allocation_units(self):
        if self.length.unit != "CHARACTERS":
            raise ValueError("character allocations cannot be imported as byte budgets")
        return self

    @field_validator("source_ref")
    @classmethod
    def safe_source(cls, value):
        parsed = urlsplit(value)
        if (parsed.scheme not in {"https", "http"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("source_ref must be an HTTP(S) source without credentials or query")
        return value


class GuideRecord(Contract):
    guide: GuideInput
    original_source: dict[str, JsonValue]
    content_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    original_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    provenance: dict[str, str]
    derived_family: str
    derivation_version: Literal["question-family-regex-v1"] = "question-family-regex-v1"
    importer_version: Literal["question-guide-import-v1"] = IMPORT_VERSION
    rights_status: Literal["REVIEW_REQUIRED"] = "REVIEW_REQUIRED"
    validation_status: Literal["IMPORTED_NOT_GLOBALLY_APPROVED"] = "IMPORTED_NOT_GLOBALLY_APPROVED"
    source_verified_live: Literal[False] = False
    reference_examples_are_applicant_facts: Literal[False] = False


class GuideRelease(Contract):
    """Server/curator review supplied separately from untrusted imported content."""

    guide_id: Text
    version: Positive
    content_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    review_id: Text
    rights: Literal["STRUCTURE_ONLY_APPROVED"]
    permitted_companies: tuple[Text, ...] = ()  # Empty means structural advice is transferable.
    semantic_status: Literal["HUMAN_REVIEWED"]
    source_rights: Literal["PUBLIC_APPROVED", "PRIVATE_REFERENCE", "RIGHTS_PENDING", "RESTRICTED"] = "RIGHTS_PENDING"


class ReleaseLedger(Contract):
    reviews: tuple[GuideRelease, ...]

    @model_validator(mode="after")
    def unique_releases(self):
        keys = [(review.guide_id, review.version, review.content_hash) for review in self.reviews]
        if len(keys) != len(set(keys)):
            raise ValueError("ambiguous duplicate guide releases; reconcile the curator ledger first")
        return self


class SourceManifest(Contract):
    namespace: Literal["QUESTION_GUIDES"] = "QUESTION_GUIDES"
    source_ref: Text
    original_payload_hash: str
    scope: Scope
    rights_status: Literal["PUBLIC_APPROVED", "PRIVATE_REFERENCE", "RIGHTS_PENDING", "RESTRICTED"]
    execution_permission: Literal["REVIEW_REQUIRED", "STRUCTURE_REFERENCE_ALLOWED", "DENIED"]
    public_example_mode: Literal["NONE"] = "NONE"
    full_text_publication_enabled: Literal[False] = False


def source_manifest(record: GuideRecord, review: GuideRelease | None = None) -> SourceManifest:
    if review and (review.guide_id, review.version, review.content_hash) != (
            record.guide.guide_id, record.guide.version, record.content_hash):
        raise ValueError("release does not match the source version")
    rights = review.source_rights if review else "RIGHTS_PENDING"
    permission = ("DENIED" if rights == "RESTRICTED" else "STRUCTURE_REFERENCE_ALLOWED"
                  if review else "REVIEW_REQUIRED")
    return SourceManifest(source_ref=record.guide.source_ref, original_payload_hash=record.original_sha256,
                          scope=record.guide.source_scope, rights_status=rights, execution_permission=permission)


def reject_personal_namespace(payload):
    """Imported metadata cannot turn user-owned Truth into a shared guide, including legacy input."""
    private_keys = {"user_id", "owner_id", "workspace_id", "private_evidence", "evidence_id", "evidence_ids",
                    "fact_id", "fact_ids", "applicant_facts", "candidate_facts", "claim_ids", "metric_ids"}
    if isinstance(payload, dict):
        if private_keys.intersection(payload):
            raise ValueError("personal Truth metadata is forbidden in the guide namespace")
        if "namespace" in payload and payload["namespace"] != "QUESTION_GUIDES":
            raise ValueError("guide namespace required")
        for value in payload.values():
            reject_personal_namespace(value)
    elif isinstance(payload, list):
        for value in payload:
            reject_personal_namespace(value)


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("non-finite JSON number")


def read_json(path: Path, *, max_bytes: int = MAX_IMPORT_BYTES) -> dict:
    # Bound the read itself, even if the file grows after stat(). No network or URL dereferencing.
    with path.open("rb") as handle:
        raw = handle.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("guide file exceeds import budget")
    payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_pairs,
                         parse_constant=_invalid_constant)
    if not isinstance(payload, dict):
        raise ValueError("guide JSON must be an object")
    return payload


def normalize(payload: dict, *, legacy: bool = False) -> GuideRecord:
    """Legacy is an explicit adapter for the already bundled mini-kit, never auto-detected."""
    reject_personal_namespace(payload)
    if legacy:
        if set(payload) - {"selection_metadata", "guide", "rules", "provenance", "source_verified_live", "namespace"}:
            raise ValueError("unexpected legacy guide fields")
        meta, original = payload["selection_metadata"], payload["guide"]
        value = {
            "guide_id": original["guide_id"], "version": 1,
            "source_ref": original["source"]["source_url"],
            "source_scope": {"company": meta["source_company"], "role": meta["source_role_name"],
                             "question_id": meta["question_id"]},
            "question": meta["original_prompt"],
            "length": {"maximum": meta["length"]["maximum_characters"]},
            "required_demands": meta["required_demands"], "question_intent": original["question_intent"],
            "allocation": [{"content": row["content"], "approximate_characters": row["approximate_characters"]}
                           for row in original["allocation"]],
        }
        provenance = {"question": "/selection_metadata/original_prompt",
                      "length": "/selection_metadata/length", "source_scope": "/selection_metadata",
                      "required_demands": "/selection_metadata/required_demands",
                      "question_intent": "/guide/question_intent", "allocation": "/guide/allocation",
                      "source_ref": "/guide/source/source_url", "guide_id": "/guide/guide_id",
                      "version": "ADAPTER_ASSIGNED:legacy-bundled-v1"}
    else:
        value = payload
        provenance = {key: f"/{key}" for key in GuideInput.model_fields}
        for optional in ("required_demands",):
            if optional not in payload:
                provenance[optional] = "DEFAULT:empty-not-inferred"
    guide = GuideInput.model_validate(value)
    original_hash = fingerprint(payload)
    content_hash = fingerprint({"guide": guide.model_dump(mode="json"), "original": original_hash,
                                "importer": IMPORT_VERSION, "provenance": provenance})
    return GuideRecord(guide=guide, original_source=payload, original_sha256=original_hash,
                       content_hash=content_hash, provenance=provenance, derived_family=family(guide.question))


def validate_record(record: GuideRecord) -> GuideRecord:
    if not isinstance(record, GuideRecord):
        raise ValueError("GuideRecord required; personal Source/Evidence cannot enter the guide catalog")
    rebuilt = normalize(record.original_source,
                        legacy=record.provenance.get("version") == "ADAPTER_ASSIGNED:legacy-bundled-v1")
    if rebuilt.model_dump(mode="json") != record.model_dump(mode="json"):
        raise ValueError("guide record hash/provenance/derived data mismatch")
    return rebuilt


def catalog(records: list[GuideRecord]) -> tuple[GuideRecord, ...]:
    """Reject split versions; expose the newest imported version, never fall back to revoked old data."""
    versions: dict[tuple[str, int], GuideRecord] = {}
    for record in records:
        record = validate_record(record)
        key = record.guide.guide_id, record.guide.version
        if key in versions and versions[key].content_hash != record.content_hash:
            raise ValueError("same guide ID/version has different content")
        versions[key] = record
    latest: dict[str, GuideRecord] = {}
    for (guide_id, version), record in sorted(versions.items()):
        latest[guide_id] = record
    return tuple(latest[key] for key in sorted(latest))


def import_file(source: Path, destination: Path, *, legacy: bool = False) -> Path:
    record = normalize(read_json(source), legacy=legacy)
    destination.mkdir(parents=True, exist_ok=True)
    # Hash filenames prevent guide identifiers from becoming filesystem paths.
    target = destination / (fingerprint([record.guide.guide_id, record.guide.version]) + ".json")
    serialized = record.model_dump_json(indent=2)
    try:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(serialized)
    except FileExistsError:
        existing = validate_record(GuideRecord.model_validate(read_json(target, max_bytes=MAX_RECORD_BYTES)))
        if existing.content_hash != record.content_hash:
            raise ValueError("immutable guide version already exists with different content") from None
    return target


def load_catalog(folder: Path) -> tuple[GuideRecord, ...]:
    return catalog([GuideRecord.model_validate(read_json(path, max_bytes=MAX_RECORD_BYTES))
                    for path in sorted(folder.glob("*.json"))])
