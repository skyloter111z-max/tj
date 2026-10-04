import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "구독모아",
  description: "구독 지출을 자동으로 모아 보고, 같이 쓸 사람을 찾습니다.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body className="min-h-screen antialiased">
        <header className="border-b border-zinc-800">
          <nav className="mx-auto flex max-w-2xl items-center justify-between px-4 py-4">
            <Link href="/" className="font-bold tracking-tight text-zinc-100">
              구독모아
            </Link>
            <div className="flex gap-4 text-sm text-zinc-400">
              <Link href="/" className="hover:text-zinc-200">
                내 구독
              </Link>
              <Link href="/party" className="hover:text-zinc-200">
                파티 찾기
              </Link>
              <Link href="/onboarding" className="hover:text-zinc-200">
                시작하기
              </Link>
            </div>
          </nav>
        </header>
        <main className="mx-auto max-w-2xl px-4 py-6 pb-20">{children}</main>
      </body>
    </html>
  );
}
