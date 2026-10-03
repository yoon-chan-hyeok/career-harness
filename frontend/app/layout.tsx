import "./style.css";
export const metadata = {
  title: "Career Harness",
  description: "근거에서 시작하는 지원 준비",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
