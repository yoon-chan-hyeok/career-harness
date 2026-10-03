"""Bounded, local document extraction followed by an explicit human decision."""

import base64
import binascii
import hashlib
import io
import re
import zipfile
import zlib
from pathlib import PurePosixPath
from typing import Literal

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfReader
from pypdf.generic import IndirectObject, StreamObject
from sqlalchemy.orm import Session

from career.models import Evidence, Source
from career.truth import add_evidence, owned, register_source, view

MAX_BYTES = 2000000
MAX_TEXT = 100000
MAX_DECODED = 30000000


class UploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=200)
    content_base64: str = Field(min_length=1, max_length=2700000)


class UploadDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: bool = False
    title: str = Field(min_length=1, max_length=200)
    kind: Literal["EVIDENCE", "EXPRESSION"] = "EVIDENCE"


def _pdf_text(raw: bytes):
    if not raw.startswith(b"%PDF-"):
        raise ValueError("PDF 파일 형식을 확인해 주세요.")
    # pypdf may inflate XRef/ObjStm during its constructor, before our stream
    # checks. This bounded importer deliberately accepts classic xref PDFs only.
    names = re.sub(rb"#[0-9a-fA-F]{2}", lambda match: bytes([int(match[0][1:], 16)]), raw)
    offsets = re.findall(rb"startxref\s+(\d+)\s+%%EOF", raw)
    if (not offsets or not raw[int(offsets[-1]):].startswith(b"xref")
            or re.search(rb"/(?:ObjStm|XRefStm|XRef)\b", names)):
        raise ValueError("압축된 PDF 구조는 지원하지 않습니다. 일반 PDF로 다시 저장하거나 DOCX로 올려 주세요.")
    reader = PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted:
        raise ValueError("암호가 없는 PDF로 저장한 뒤 올려 주세요.")
    # Validate compressed streams before the text extractor can expand them.
    decoded_total = 0
    object_count = sum(len(objects) for objects in reader.xref.values())
    if object_count > 15000:
        raise ValueError("문서 구조가 너무 큽니다. 필요한 페이지를 나누어 올려 주세요.")
    for generation, objects in reader.xref.items():
        for object_id in objects:
            if not object_id:
                continue
            obj = reader.get_object(IndirectObject(object_id, generation, reader))
            if not isinstance(obj, StreamObject):
                continue
            # Raster images are not decoded or sent to an OCR service.
            if obj.get("/Subtype") == "/Image":
                continue
            data = obj._data
            filters = obj.get("/Filter")
            for filter_name in (filters if isinstance(filters, list) else [filters]):
                if filter_name == "/FlateDecode":
                    inflater = zlib.decompressobj()
                    data = inflater.decompress(data, MAX_DECODED - decoded_total + 1)
                    if inflater.unconsumed_tail or not inflater.eof:
                        raise ValueError("압축된 문서 내용이 너무 큽니다.")
                elif filter_name == "/ASCII85Decode":
                    data = base64.a85decode(data.strip(), adobe=data.strip().endswith(b"~>"))
                elif filter_name == "/ASCIIHexDecode":
                    value = re.sub(rb"\s+", b"", data).rstrip(b">")
                    data = bytes.fromhex((value + (b"0" if len(value) % 2 else b"")).decode("ascii"))
                elif filter_name is not None:
                    raise ValueError("지원하지 않는 PDF 압축 형식입니다. 일반 PDF로 다시 저장해 주세요.")
            decoded_total += len(data)
            if decoded_total > MAX_DECODED:
                raise ValueError("추출할 문서 내용이 너무 큽니다.")
    if len(reader.pages) > 40:
        raise ValueError("최대 40페이지입니다. 필요한 페이지만 나누어 올려 주세요.")
    pages = []
    count = 0
    for number, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        count += len(text)
        if count > MAX_TEXT:
            raise ValueError("추출 문자는 최대 100,000자입니다.")
        pages.append({"number": number, "text": text})
    text = "\n\n".join(page["text"] for page in pages).strip()
    if not text:
        raise ValueError("읽을 수 있는 텍스트가 없습니다. 스캔 PDF는 OCR을 적용한 뒤 올려 주세요.")
    warnings = ["PDF의 읽기 순서·표·줄바꿈은 원본과 다를 수 있습니다. 추출 내용을 확인해 주세요."]
    if any(not page["text"].strip() for page in pages):
        warnings.append("텍스트를 읽지 못한 페이지가 있습니다. 이미지의 내용은 추출하지 않았습니다.")
    return text, pages, warnings


def _docx_text(raw: bytes):
    if not raw.startswith(b"PK"):
        raise ValueError("DOCX 파일 형식을 확인해 주세요.")
    warnings = ["Word의 페이지 배치는 추출하지 않습니다. 본문·표·줄바꿈을 확인해 주세요."]
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if len(entries) > 1500 or sum(item.file_size for item in entries) > MAX_DECODED:
            raise ValueError("문서 내부 크기가 너무 큽니다.")
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if (path.is_absolute() or ".." in path.parts or "\\" in entry.filename
                    or entry.file_size > 10000000 or entry.flag_bits & 1
                    or entry.file_size > max(1, entry.compress_size) * 500):
                raise ValueError("안전하게 읽을 수 없는 DOCX 구조입니다.")
            lowered = entry.filename.lower()
            if "vbaproject" in lowered or "/embeddings/" in lowered or "altchunk" in lowered:
                raise ValueError("매크로·삽입 실행 파일을 제거한 DOCX로 올려 주세요.")
            if lowered.endswith((".xml", ".rels")):
                xml = archive.read(entry)
                if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
                    raise ValueError("외부 XML 선언이 있는 문서는 읽을 수 없습니다.")
                if lowered.endswith(".rels"):
                    # Only plain hyperlinks may remain; python-docx never follows them.
                    from xml.etree import ElementTree
                    for relation in ElementTree.fromstring(xml):
                        if relation.attrib.get("TargetMode") == "External":
                            if not relation.attrib.get("Type", "").endswith("/hyperlink"):
                                raise ValueError("외부 파일 참조를 제거한 DOCX로 올려 주세요.")
                            if "외부 링크는 열거나 전송하지 않았습니다." not in warnings:
                                warnings.append("외부 링크는 열거나 전송하지 않았습니다.")
    document = Document(io.BytesIO(raw))
    parts = []
    count = 0
    for element in document.element.body:
        previous = len(parts)
        if element.tag.endswith("}p"):
            parts.append(Paragraph(element, document).text)
        elif element.tag.endswith("}tbl"):
            for row in Table(element, document).rows:
                parts.append(" | ".join(cell.text for cell in row.cells))
        count += sum(len(value) for value in parts[previous:])
        if count > MAX_TEXT:
            raise ValueError("추출 문자는 최대 100,000자입니다.")
    text = "\n".join(parts).strip()
    if not text:
        raise ValueError("읽을 수 있는 본문이 없습니다. 텍스트가 있는 문서를 올려 주세요.")
    return text, [], warnings


def upload_preview(db: Session, user: str, body: UploadRequest):
    filename = body.filename.replace("\\", "/").split("/")[-1]
    if not filename or re.search(r"[\x00-\x1f]", filename):
        raise ValueError("파일 이름을 확인해 주세요.")
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix not in {".pdf", ".docx", ".txt", ".md"}:
        raise ValueError("PDF·DOCX·TXT·MD 파일을 올려 주세요.")
    try:
        raw = base64.b64decode(body.content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("파일 데이터 형식을 확인해 주세요.") from None
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("파일은 최대 2MB입니다.")
    try:
        if suffix == ".pdf":
            text, pages, warnings = _pdf_text(raw)
        elif suffix == ".docx":
            text, pages, warnings = _docx_text(raw)
        else:
            text, pages, warnings = raw.decode("utf-8-sig").strip(), [], []
            if not text or len(text) > MAX_TEXT or "\x00" in text:
                raise ValueError("UTF-8 텍스트의 길이와 내용을 확인해 주세요.")
    except ValueError:
        raise
    except Exception:
        # Parser errors may contain source text and local paths.
        raise ValueError("문서를 읽지 못했습니다. 파일이 손상되었는지 확인해 주세요.") from None
    binary_hash = hashlib.sha256(raw).hexdigest()
    source, added = register_source(db, user, "uploads/" + binary_hash + suffix, text, "UPLOAD_PREVIEW", {
        "upload": {"filename": filename, "bytes": len(raw), "binary_hash": binary_hash,
                   "text": text, "pages": pages, "warnings": warnings, "confirmed": False,
                   "original_base64": body.content_base64},
    })
    if added:
        source.status = "UNVERIFIED"
    elif source.status in {"DO_NOT_USE", "SUPERSEDED"}:
        raise ValueError("폐기한 파일입니다. 현재 유효한 자료를 올려 주세요.")
    upload = source.data["upload"]
    return {"id": source.id, "filename": upload["filename"], "text": upload["text"],
            "pages": upload["pages"], "warnings": upload["warnings"],
            "status": "CONFIRMED" if upload.get("confirmed") else "PREVIEW"}


def confirm_upload(db: Session, user: str, source_id: str, decision: UploadDecision):
    source = owned(db, Source, user, source_id)
    upload = source.data.get("upload")
    if not upload or source.status in {"DO_NOT_USE", "SUPERSEDED"}:
        raise ValueError("등록할 파일 미리보기를 다시 선택해 주세요.")
    if not decision.confirmed:
        raise ValueError("추출 내용을 직접 확인한 뒤 등록해 주세요.")
    signature = {"title": decision.title.strip(), "kind": decision.kind}
    if not signature["title"]:
        raise ValueError("자료 제목을 입력해 주세요.")
    if upload.get("confirmed"):
        if upload.get("decision") != signature:
            raise ValueError("이미 등록한 파일입니다. 기존 자료에서 수정해 주세요.")
        evidence = owned(db, Evidence, user, upload["evidence_id"])
    else:
        source.authority = "APPLICATION" if decision.kind == "EXPRESSION" else "MEMORY"
        source.status = "SOURCE_BACKED"
        evidence = add_evidence(db, user, source.id, signature["title"], upload["text"],
                                {"upload_source_id": source.id, "ownership": "UNKNOWN"},
                                kind=decision.kind, status="UNVERIFIED")
        source.data = {**source.data, "upload": {**upload, "confirmed": True, "decision": signature,
                                                 "evidence_id": evidence.id}}
    return {"source_id": source.id, "evidence": view(evidence), "notice":
            "원자료로 등록했습니다. 사실·수치·본인 수행 범위는 경험 정리에서 별도로 확인해 주세요."}
