"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { PublicFooter } from "./public-entry";
import {
  loadPublicService,
  providerNames,
  type PublicService,
} from "./public-service";

export function PublicPolicy({ kind }: { kind: "privacy" | "terms" }) {
  const [service, setService] = useState<PublicService | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    loadPublicService()
      .then((value) => {
        if (active) setService(value);
      })
      .catch((error) => {
        if (active)
          setError(
            error instanceof Error
              ? error.message
              : "안내를 불러오지 못했습니다.",
          );
      });
    return () => {
      active = false;
    };
  }, []);
  const ready =
    service?.policy_version &&
    (service?.guest_enabled
      ? service.support_url
      : service?.operator_name && service?.support_email);
  return (
    <main className="public-page">
      <header className="public-header">
        <Link href="/" className="brand">
          Career Harness
        </Link>
        <Link href="/workspace">작업실로 돌아가기 →</Link>
      </header>
      <article className="policy-document">
        <h1>{kind === "privacy" ? "개인정보 처리방침" : "이용약관"}</h1>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        {!service && !error && (
          <p role="status">운영 안내를 불러오는 중입니다…</p>
        )}
        {service && !ready && (
          <p role="status">
            운영자·문의처·안내 버전이 아직 확정되지 않아 공개 서비스의 이용
            안내를 제공할 수 없습니다. 공개 가입 전에 운영 정보를 확인해 주세요.
          </p>
        )}
        {service && ready && (
          <>
            <p className="muted">
              {service.guest_enabled && !service.operator_name
                ? "Career Harness 공개 체험"
                : `운영자: ${service.operator_name}`}{" "}
              · 안내 버전: {service.policy_version}
            </p>
            {kind === "privacy" ? (
              <>
                <h2>1. 처리하는 정보와 목적</h2>
                <p>
                  {service.guest_enabled
                    ? "임의로 발급한 체험 식별자는 작업실별 접근 제어에"
                    : "이메일과 계정 식별자는 본인 확인과 계정별 접근 제어에"}
                  사용합니다. 사용자가 입력하거나 업로드한 경험, 프로필, 채용
                  공고, 자기소개서, 이력서, 대화와 작성 기록은 근거 정리·문서
                  작성·검수·보관에 사용합니다. 사용량, 실행 상태, 동의·삭제
                  기록은 한도 관리, 오류 대응, 부정 이용 방지에 사용합니다.
                </p>
                <h2>2. 외부 서비스 처리</h2>
                <p>
                  {service.guest_enabled
                    ? "현재 체험에서는 이메일을 수집하지 않으며 Supabase에 작업 자료를 저장합니다. 접속 주소에서 만든 비가역 식별자는 체험 생성 한도에 사용합니다."
                    : "Supabase가 이메일 인증과 데이터베이스 저장을 제공합니다. Cloudflare Turnstile은 로그인 과정의 봇 방지를 위해 기기·네트워크 정보를 처리합니다."}{" "}
                  웹 호스팅 사업자는 접속 요청을 처리하며, 배포 환경의 운영
                  로그가 남을 수 있습니다.
                </p>
                <p>
                  현재 AI 제공자:{" "}
                  <strong>
                    {providerNames[service.ai_provider] ||
                      service.ai_provider ||
                      "미연결"}
                  </strong>
                  . AI 기능을 실행하면 해당 작업에 필요한 입력 문서와 근거가 이
                  제공자에게 전송됩니다. Hugging Face를 사용할 경우 선택된 추론
                  제공자가 처리할 수 있습니다. 외부 제공자의 처리 지역·보관·학습
                  이용 조건은 해당 제공자의 정책에 따르므로, 전송하면 안 되는
                  자료는 입력하지 마세요.
                </p>
                <h2>3. 보관과 삭제</h2>
                <p>
                  {service.guest_enabled ? (
                    "체험 연결은 24시간 동안 사용할 수 있고 같은 브라우저 탭에서만 이어집니다. 만료 자료는 이후 방문 시 순차 정리하며 정확한 시각의 삭제를 보장하지 않습니다. 설정에서 직접 삭제할 수도 있습니다. 앱에서 체험 자료의 별도 자동 백업을 만들지 않으며 외부 사업자의 인프라·로그 보관 조건은 각 제공자의 정책에 따릅니다."
                  ) : (
                    <>
                      계정을 유지하는 동안 지원 준비를 위해 저장하며, 사용자가
                      자료나 계정을 삭제할 때 삭제 절차를 진행합니다. 비활성
                      계정을 자동 삭제하는 기능은 운영하지 않습니다.{" "}
                      {service.backup_retention_days === null
                        ? "백업 보관 기간은 아직 공개 운영 설정에서 확정되지 않았습니다."
                        : `운영자가 설정한 백업 보관 기간은 ${service.backup_retention_days}일입니다.`}{" "}
                      백업 보관 기간은 운영자가 적용하는 정책이며 앱이 자동으로
                      백업을 제거한다는 의미는 아닙니다.
                    </>
                  )}
                </p>
                <p>
                  {service.guest_enabled ? (
                    "체험 자료 삭제를 요청하면 해당 작업실의 자료와 연결 정보를 삭제하고 즉시 접근을 차단합니다. 과다 사용 방지를 위한 최소 집계와 삭제 처리 기록은 남습니다."
                  ) : (
                    <>
                      계정 삭제를 요청하면 작업실 접근을 중지하고
                      경험·문서·대화·제출본과 인증 계정을 삭제합니다. 재접근
                      차단과 과다 사용 방지를 위한 최소 기록, 사용량 집계와 삭제
                      처리 기록은 별도로 남습니다. 이미 생성된 백업의 사본은
                      운영자가 정한 보관 기간에 따라 제거하고, 백업 복구 시 삭제
                      요청을 다시 적용해야 합니다.
                    </>
                  )}
                </p>
                <h2>4. 이용자의 선택과 요청</h2>
                <p>
                  설정의 ‘내 자료 전체 내려받기’로 자료를 받을 수 있고,
                  원자료·지원 작업을 개별 삭제하거나{" "}
                  {service.guest_enabled
                    ? "현재 체험 연결에서"
                    : "이메일로 본인 확인 후"}
                  계정을 삭제할 수 있습니다. 정보 열람·정정·삭제 또는 처리 관련
                  문의는 아래 연락처로 요청해 주세요.
                </p>
                <h2>5. 입력 자료와 변경 안내</h2>
                <p>
                  주민등록번호, 계좌 정보, 본인에게 이용 권한이 없는 개인정보나
                  기밀은 입력하지 마세요. 주요 이용 안내가 변경되면 새 안내
                  버전에 동의하기 전까지 작업실 이용을 제한할 수 있습니다.
                </p>
              </>
            ) : (
              <>
                <h2>1. 서비스와 계정</h2>
                <p>
                  {service.guest_enabled
                    ? "Career Harness 공개 체험은"
                    : `${service.operator_name}는 Career Harness를 통해`}{" "}
                  경험 정리, 공고 분석, 자기소개서·이력서 작성과 검수·보관을
                  지원합니다.
                  {service.guest_enabled
                    ? "작업 공간은 현재 브라우저 탭의 24시간 체험 연결에 묶이며 탭 종료·로그아웃·만료 후 복구할 수 없습니다. 필요한 자료는 직접 내려받아 보관해야 합니다. "
                    : "본인이 사용할 수 있는 이메일로 인증해야 하며, "}{" "}
                  다른 사람의 계정이나 자료에 접근해서는 안 됩니다.
                </p>
                <h2>2. 이용 조건과 한도</h2>
                <p>
                  현재 신규 가입은{" "}
                  {service.registration_open
                    ? "열려 있습니다"
                    : "중단되어 있습니다"}
                  . 기본 AI 실행 한도는 하루 {service.public_limits.daily_calls}
                  회, 월 {service.public_limits.monthly_calls}회이며 개인별 토큰
                  한도와 서비스 전체 공용 한도도 적용됩니다. 제공자의 무료 한도,
                  장애, 보안 대응으로 사용이 제한되거나 중단될 수 있습니다. 자동
                  유료 전환이나 무제한 AI 제공을 약속하지 않습니다.
                </p>
                <h2>3. 문서와 AI 결과</h2>
                <p>
                  자료에 대한 이용 권한은 사용자에게 있어야 합니다. AI 결과의
                  사실·수치·기여 범위·적합성을 직접 검토하고 제출 여부를
                  결정해야 합니다. 서비스는 채용 결과나 생성 내용의 정확성을
                  보장하지 않으며 지원서를 자동 제출하지 않습니다.
                </p>
                <h2>4. 금지되는 이용</h2>
                <p>
                  계정 공유를 통한 한도 회피, 자동 대량 가입, 다른 사람의
                  개인정보·기밀 무단 입력, 서비스 공격이나 부정한 접근을
                  금지합니다. 운영자는 부정 이용이나 장애 확산을 막기 위해
                  접근을 제한할 수 있습니다.
                </p>
                <h2>5. 종료와 안내</h2>
                <p>
                  설정에서 자료를 내려받고 계정을 삭제할 수 있습니다. 필요한
                  자료는 직접 보관해 주세요. 보관·삭제와 외부 서비스 처리는
                  개인정보 처리방침을 따릅니다. 서비스나 이용 조건의 중요한
                  변경은 서비스 안내와 이용 시 동의 절차를 통해 알립니다.
                </p>
              </>
            )}
            <h2>문의</h2>
            <p>
              {service.support_email && (
                <>
                  {service.operator_name} ·{" "}
                  <a href={"mailto:" + service.support_email}>
                    {service.support_email}
                  </a>
                </>
              )}
              {service.guest_enabled && (
                <>
                  {" "}
                  ·{" "}
                  <a
                    href={service.support_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    GitHub 오류 제보
                  </a>
                </>
              )}
            </p>
          </>
        )}
      </article>
      {service && <PublicFooter service={service} />}
    </main>
  );
}
