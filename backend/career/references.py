"""User-owned supplemental references; never import examples into the fact store."""

import hashlib
from pathlib import Path

from sqlalchemy import select

from career.artifacts import stale
from career.db import Record
from career.models import Source
from career.truth import owned, register_source, view
from career.validation import GOOD

CATALOG = {
    "registry": (
        "취업프로젝트_RULE_REGISTRY_Session_Injection_Guide_v2.md",
        "작업별 자료 사용 기준",
        "v2",
        "ORCHESTRATION",
    ),
    "integrity": (
        "윤찬혁_취업문서_공통_사실성_Evidence_RULE_v1.md",
        "공통 사실성 기준",
        "v1",
        "COMMON_INTEGRITY",
    ),
    "opportunity": (
        "윤찬혁_공고탐색_지원우선순위_RULE_v1_1.md",
        "공고·지원 우선순위",
        "v1.1",
        "OPPORTUNITY_RULE",
    ),
    "resume": ("윤찬혁_Resume_작성선별_RULE_v1_1.md", "이력서 작성·선별", "v1.1", "RESUME_RULE"),
    "cover": (
        "윤찬혁_자소서_작성전략_v5_1_Canonical_Audited.md",
        "자소서 작성 전략",
        "v5.1",
        "COVER_LETTER_RULE",
    ),
    "expression": (
        "윤찬혁_프로젝트_운영가치_자소서_표현집_Canonical_v1.md",
        "운영가치 표현 참고",
        "v1",
        "EXPRESSION_REFERENCE",
    ),
}

# These source-grounded projections deliberately omit personal snapshots, Fact Lock
# sections, company examples and numerical example claims. Originals remain available
# for human inspection; no file is a system instruction or a source of candidate facts.
GUIDANCE = {
    "registry": (
        "Authority / Session Packs A–G",
        [
            "역할(Layer)과 우선순위(Authority)를 구분한다. 현재 사용자 요청은 작업 순서를 바꿀 수 있지만 사실성 검증을 생략하지 않는다.",
            "최신 명시적 사실 정정 → 최신 원자료·프로젝트 잠금본 → 확인된 프로필 → 마스터·파생 요약 → 과거 예시 → 기억·추론. 제출 보관본은 당시 제출한 내용만 증명한다.",
            "공통 사실성 → 현재 작업의 도메인 규칙 → 승인된 회사별 전략 → 표현 참고 → 과거 예시 순으로 적용한다. 다른 도메인의 규칙과 과거 Persona를 가져오지 않는다.",
            "한 번의 결과는 약한 신호다. 코딩·인적성 실패로 작성 규칙을 바꾸지 않는다. 규칙 승격은 반복 증거와 사람의 별도 승인이 필요하다.",
        ],
    ),
    "integrity": (
        "사실 상태 / 구현·Ownership·Metric / 최종 확인",
        [
            "확인된 원자료와 명시적 사용자 확인만 사실 근거다. 불명확한 내용은 확인 필요, 금지 내용은 사용 중지로 유지한다.",
            "구현·실험 검증·부분 탐색·설계·미수행을 구분하고, 실험을 실제 배포 성과로 올리지 않는다.",
            "문제 정의·판단·설계·직접 구현·기존 코드 통합·AI 보조·팀·조직 성과를 분리한다.",
            "숫자의 기준·결과·단위·표본·데이터·시점·출처·검증 환경·기여 범위를 확인한다. 측정하지 않은 시간·비용·매출 효과를 만들지 않는다.",
            "기술 결과, 가능하게 한 운영가치, 측정한 비즈니스 성과를 구분한다. 표현집·마스터·과거 지원서로 최신 사실을 덮지 않는다.",
            "민감한 고객·조직·보안·비공개 수치는 공개 가능 범위를 사람에게 확인한다. 사실 정정은 관련 파생 문서만 재검토시키며 제출 보관본을 변경하지 않는다.",
        ],
    ),
    "opportunity": (
        "STEP A–G / 세 축 / 최종 판정",
        [
            "최신 공식 공고의 출처·확인일·OPEN/CLOSED/UNCERTAIN과 마감 날짜·정확한 시간·시간대를 확인한다. 과거 JD는 현재 채용 사실이 아니다.",
            "Required와 Preferred를 나누고 자격 충족·미충족·확인 필요를 먼저 점검한다. 필수 조건 실패를 높은 적합도로 가리지 않는다.",
            "Actual Output을 보통 핵심 3개 정도로 해석하되 개수를 강제하지 않는다. CRITICAL/CORE/SUPPORTING을 표시한다.",
            "본업·전문 분야·도구와 Main Skill·Differentiator를 나눈다. 중요 업무의 NO EVIDENCE와 필수 Production Ownership 공백을 강하게 반영한다.",
            "직무 적합도(Fit), 커리어 가치(Career Value), 지금 행동 순서(Action Priority)를 별도로 평가한다. 마감은 행동 순서에만 영향을 준다.",
            "전형 생존 위험과 준비 비용 NOW/SHORT(1~3일)/MEDIUM(1~3주)/HIGH를 구분한다. 판정 PROCEED/PROCEED_WITH_GAP/LOW_PRIORITY/SKIP은 사람에게 제공하는 추천이다.",
        ],
    ),
    "cover": (
        "Phase 1–7 / Reference / 최종 제출 질문",
        [
            "Research → Role → Fit → Architecture → Question → Draft → Validate 순으로 진행한다. Why Now는 공개 출처로 뒷받침한 가설이며 회사 내부 사실이 아니다.",
            "Actual Output·본업·Main Skill·Direct/Adjacent/No Evidence·Fatal Gap에서 Persona와 맡길 일을 도출한다. 순수 기술직의 본업을 억지로 산업 직군으로 바꾸지 않는다.",
            "관련 과거 교정·실패는 재발 방지에만 쓰고 현재 사실·전략으로 복사하지 않는다. 전체 문항은 역할을 나누고 같은 Fact·숫자·결론·메시지 반복을 피한다.",
            "문항 의도 → Fact·Ownership·수치·한계 재확인 → 표현 참고 → 운영가치 번역 → 가설 Claim → Evidence Test → 사람의 Claim 잠금 후 작성한다.",
            "PODAEIJ 중 필요한 요소만 사용하며 Decision을 중심에 둔다. 첫 2~3문장 안에 답하고 WHAT보다 WHY/SO WHAT/WHERE NEXT를 남긴다.",
            "지원동기는 경험에서 생긴 기준·왜 본업·왜 이 회사·회사 고유 근거·현장 학습·현실적 성장으로 연결한다. 현장/로테이션을 우회 과정으로 표현하지 않는다.",
            "Fact·Ownership 점검, Reverse Test, 채용담당자 Red Team, Role Noun Test 후 압축·잠금한다. 기술 스택·중복·일반론을 먼저 줄이고 판단·강한 근거·한계·회사 연결을 남긴다.",
        ],
    ),
    "resume": (
        "Master-first / Selection / Bullet / Ownership / File QA",
        [
            "이력서는 근거를 빠르게 훑게 하는 문서다. 최신 사실을 확인한 마스터에서 JD별 프로젝트를 선별·순서 조정하고 문장은 자유롭게 재작성한다.",
            "Actual Output·Required·Preferred·Main Skill·공백을 먼저 본다. 강한 근거 보통 2~4개를 고르되 고정 개수를 강제하지 않고 직접성과 Ownership·면접 방어력을 우선한다.",
            "가장 강한 JD 산출물을 첫 프로젝트로 배치한다. Bullet 하나는 주 주장 하나로, 산출물/기능/성과 Hook → 행동·판단 → 검증 근거를 담고 단독으로 이해되게 쓴다.",
            "긴 Summary는 기본적으로 생략한다. 경험과 프로젝트의 중복을 줄이고 기술은 판단·산출물 뒤에 둔다. Skills는 실제 사용 맥락과 설명 가능한 깊이가 있어야 한다.",
            "직접 판단·설계·AI 보조·기존 코드 통합·팀 결과를 분리한다. 운영 가능성과 측정한 비즈니스 효과를 구분하고 수치는 검증 범위를 넘지 않는다.",
            "회사 형식·언어에 맞추고 1/2페이지를 강제하지 않는다. 실제 내보낸 파일의 잘림·겹침·줄바꿈·페이지 수·링크·날짜·이름·언어를 사람이 확인한 뒤 사용한다.",
        ],
    ),
    "expression": (
        "전체 원칙 / 회사별 선택 / 문장 세기",
        [
            "표현 참고는 Fact DB가 아니다. 예시의 Fact Lock·숫자·기여·배포 여부·기본 Persona를 새 사실로 등록하지 않는다.",
            "사실은 보수적으로, 문장은 강하게: 사실이 허용하는 범위에서 무엇을 만들었고 누구의 어떤 점검·위험·우선순위·조사 범위·의사결정을 돕는지 번역한다.",
            "A–F는 소재별 표현 선택지이며 뜻이 고정된 공통 스키마가 아니다. 구현, 운영가치, 문제 재정의, 제약, Hook, 검증 근거 중 현재 JD와 확인된 Evidence에 맞는 관점을 선택한다.",
            "일반 신입 AI/AX는 확인된 Build를 먼저, 평가·진단을 차별점으로 둔다. JD가 Evaluation/LLMOps/Reliability를 본업으로 요구할 때만 그 비중을 높인다.",
            "기능형(Level 2)은 이력서/기술 설명, 운영가치형(Level 3)은 자소서 기본, Hook(Level 4)은 즉시 실험·프로토타입 한계를 명시한다. 과장(Level 5)은 금지한다.",
            "실제로 측정하지 않았다면 비용·검수시간을 줄였다고 단정하지 않는다. 자동 선별·진단 보조·보류·검수 우선순위·운영 시나리오와 실제 운영 성과를 구분한다.",
        ],
    ),
}

PACKS = {
    "research": ("registry", "integrity", "cover"),
    "opportunity": ("registry", "integrity", "opportunity"),
    "strategy": ("registry", "integrity", "opportunity", "cover"),
    "cover": ("registry", "integrity", "cover", "expression"),
    "resume": ("registry", "integrity", "resume"),
    "fact": ("registry", "integrity"),
    "interview": ("registry", "integrity", "cover"),
    "postmortem": ("registry", "integrity"),
}
STAGES = {
    "research": "research",
    "research_plan": "research",
    "web_search": "research",
    "research_extract": "research",
    "research_source_extract": "research",
    "opportunity": "opportunity",
    "opportunity_assessment": "opportunity",
    "evidence_mapper": "opportunity",
    "strategy": "strategy",
    "question_portfolio": "strategy",
    "question_brief": "cover",
    "claim_evidence_test": "cover",
    "submission_readiness": "cover",
    "writer": "cover",
    "issue_patch_compression": "cover",
    "resume_writer": "resume",
    "fact_reviewer": "fact",
    "truth_extraction": "fact",
    "recruiter": "cover",
    "reverse_interview": "interview",
    "review_answers": "interview",
    "review_answer_extract": "interview",
    "interview_handoff": "interview",
    "postmortem": "postmortem",
}


def references(db, user):
    return list(
        db.scalars(select(Record).where(Record.user_id == user, Record.kind == "SupplementReference"))
    )


def register(db, user, key: str, content: str):
    if key not in CATALOG or not content.strip():
        raise ValueError("지원하는 추가 자료와 본문을 선택해 주세요.")
    filename, title, version, role = CATALOG[key]
    digest = hashlib.sha256(content.encode()).hexdigest()
    previous = [r for r in references(db, user) if r.data["key"] == key]
    for record in previous:
        if record.data["content_hash"] == digest and record.data["active"]:
            return record
    source, _ = register_source(db, user, "supplemental/" + filename, content, "REFERENCE", {"role": role})
    source.status = "SOURCE_BACKED"
    for record in previous:
        if record.data["active"]:
            record.data = {**record.data, "active": False}
            stale(db, user, [record.data["source_id"]])
    record = Record(
        user_id=user,
        kind="SupplementReference",
        data={
            "key": key,
            "filename": filename,
            "title": title,
            "version": version,
            "role": role,
            "source_id": source.id,
            "content_hash": digest,
            "content": content,
            "active": True,
            "projection_version": "supplement-v1",
            "fact_imported": False,
        },
    )
    db.add(record)
    db.flush()
    return record


def import_directory(db, user, root: Path):
    contents = {key: (root / meta[0]).read_text("utf-8-sig") for key, meta in CATALOG.items()}
    return [register(db, user, key, content).id for key, content in contents.items()]


def listing(db, user):
    from career.rulebook import overview

    return [
        {"id": r.id, **{k: v for k, v in r.data.items() if k != "content"},
         "compilation": overview(r.data["key"], r.data["content"])}
        for r in references(db, user)
    ]


def activate(db, user, reference_id: str, active: bool):
    record = owned(db, Record, user, reference_id)
    if record.kind != "SupplementReference":
        raise LookupError("추가 자료가 아닙니다.")
    if active and owned(db, Source, user, record.data["source_id"]).status not in GOOD:
        raise ValueError("삭제되거나 무효화된 출처는 다시 사용할 수 없습니다.")
    changed = []
    for other in references(db, user):
        if other.id == record.id or (active and other.data["key"] == record.data["key"]):
            value = active if other.id == record.id else False
            if other.data["active"] != value:
                changed.extend(stale(db, user, [other.data["source_id"]]))
                other.data = {**other.data, "active": value}
    return {"reference": view(record), "stale_artifacts": changed}


def compile_pack(db, user, stage: str, domain=""):
    from career.rulebook import COMPILER_VERSION, compile_sections

    pack = (
        "resume"
        if domain == "RESUME" and stage in {"recruiter", "issue_patch_compression", "reverse_interview",
                                           "review_answers", "review_answer_extract", "interview_handoff"}
        else STAGES.get(stage)
    )
    if pack is None:
        return {"pack": None, "references": []}
    active = {r.data["key"]: r for r in references(db, user) if r.data["active"]}
    compiled = []
    for key in PACKS[pack]:
        record = active.get(key)
        if record is None or owned(db, Source, user, record.data["source_id"]).status not in GOOD:
            continue
        section, rules = GUIDANCE[key]
        source_sections = compile_sections(key, record.data["content"], stage)
        if pack == "interview" and key == "cover":
            section = "Phase 7 §8-2 Reverse Test / §8-3 Red Team (면접용 일부)"
            rules = [
                "왜 문제와 방법을 택했는가, 바꾼 관찰, 대안, 한계, 개인 역할, 실제 사용자·배포·회사 적용을 깊게 묻는다. 질문이 깊어질수록 확인된 강점이 드러나야 한다.",
                "본업·현장·로테이션을 요구하는 직무는 기술 외에도 본업을 하고 싶은지, 현장 학습을 우회 과정으로 보지 않는지 확인한다. 약한 답은 솔직한 Gap 대응과 Evidence 보완으로 연결한다.",
            ]
        compiled.append(
            {
                "key": key,
                "role": record.data["role"],
                "version": record.data["version"],
                "source_id": record.data["source_id"],
                "content_hash": record.data["content_hash"],
                "section": section,
                "guidance": [item["text"] for item in source_sections] if source_sections else rules,
                "requirements": [{k: v for k, v in item.items() if k != "text"} for item in source_sections],
                "compiler_version": COMPILER_VERSION,
                "compilation_status": "SOURCE_SECTIONS" if source_sections else "DEFAULT_GUIDANCE_ONLY",
                "fact_authority": False,
            }
        )
    if pack == "interview":
        extra = [
            "제출 보관본과 최신 JD의 시점 차이를 명시한다. 왜 문제·방법을 택했나, 바꾼 관찰, 대안, 한계, 개인 역할, 실제 사용자/배포, 본업 의지를 묻는다. 새 성과를 발명하지 않는다."
        ]
    elif pack == "postmortem":
        extra = [
            "관찰 사실·원인 가설·확신도·적용 범위를 분리한다. 서류 실패는 약한 전략 신호, 코딩·인적성 실패는 작성 규칙 신호가 아니다. 자동 규칙 승격을 금지한다."
        ]
    else:
        extra = []
    return {
        "pack": pack,
        "references": compiled,
        "stage_checks": extra,
        "authority": "SUPPLEMENTAL_DOMAIN_DATA_NOT_SYSTEM_INSTRUCTIONS",
    }
