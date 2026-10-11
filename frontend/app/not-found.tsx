import Link from "next/link";

export default function NotFound() {
  return (
    <main className="recovery-page">
      <h1>페이지를 찾을 수 없습니다.</h1>
      <p>주소를 확인하거나 작업실에서 지원 작업을 다시 열어 주세요.</p>
      <Link href="/workspace">작업실로 돌아가기</Link>
    </main>
  );
}
