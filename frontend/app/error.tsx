"use client";
import Link from "next/link";

export default function ErrorPage({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="recovery-page">
      <h1>화면을 불러오지 못했습니다.</h1>
      <p>
        다시 열어 저장된 작업을 확인해 주세요. 아직 저장하지 않은 입력은 복구
        여부를 확인해야 합니다.
      </p>
      <button onClick={reset}>다시 불러오기</button>
      <Link href="/workspace">작업실로 돌아가기</Link>
    </main>
  );
}
