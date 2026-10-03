import Link from "next/link";
import {
  detectSubscriptions,
  daysUntilCharge,
  monthlyEquivalent,
  totalMonthly,
} from "@/lib/detector";
import { KNOWN_KEYS, SAMPLE_TRANSACTIONS } from "@/lib/sample-data";

const won = (n: number) => `${n.toLocaleString("ko-KR")}원`;
const TODAY = "2026-10-03";

const CYCLE_LABEL = { weekly: "주", monthly: "월", yearly: "연" } as const;

export default function HomePage() {
  // 운영 시에는 오픈뱅킹 월 1회 배치 결과를 넣는다. 지금은 샘플 거래로 엔진을 돌린다.
  const subs = detectSubscriptions(SAMPLE_TRANSACTIONS, {
    today: TODAY,
    knownKeys: KNOWN_KEYS,
  });
  const monthly = totalMonthly(subs);
  const newSubs = subs.filter((s) => s.isNew);
  const upcoming = [...subs]
    .filter((s) => daysUntilCharge(s, TODAY) >= 0)
    .sort((a, b) => daysUntilCharge(a, TODAY) - daysUntilCharge(b, TODAY));

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-6">
        <p className="text-xs font-medium text-zinc-500">이번 달 구독 지출</p>
        <p className="mt-1 text-3xl font-bold tracking-tight text-zinc-50">{won(monthly)}</p>
        <p className="mt-1 text-sm text-zinc-400">
          구독 {subs.length}개 · 연 {won(monthly * 12)}
        </p>
      </section>

      {newSubs.length > 0 && (
        <section className="rounded-2xl border border-amber-500/30 bg-amber-500/5 p-5">
          <h2 className="text-sm font-bold text-amber-300">새로 생긴 정기결제 {newSubs.length}개</h2>
          <p className="mt-1 text-xs text-amber-200/70">
            무료 체험이 유료로 바뀐 것일 수 있습니다.
          </p>
          <ul className="mt-3 space-y-1.5">
            {newSubs.map((s) => (
              <li key={s.merchantNormalized} className="flex justify-between text-sm">
                <span className="text-zinc-200">{s.displayName}</span>
                <span className="font-semibold text-zinc-100">
                  {won(s.amount)}/{CYCLE_LABEL[s.cycle]}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="space-y-3">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
          결제 예정
        </h2>
        {upcoming.map((s) => {
          const d = daysUntilCharge(s, TODAY);
          return (
            <div
              key={s.merchantNormalized}
              className="flex items-center justify-between rounded-xl border border-zinc-800 bg-zinc-900/40 px-4 py-3"
            >
              <div className="min-w-0">
                <p className="truncate font-medium text-zinc-100">{s.displayName}</p>
                <p className="mt-0.5 text-xs text-zinc-500">
                  {s.nextChargeDate}
                  {s.priceChange && (
                    <span className="ml-2 text-amber-400">
                      {won(s.priceChange.from)} → {won(s.priceChange.to)}
                    </span>
                  )}
                  {s.confidence < 0.6 && (
                    <span className="ml-2 text-zinc-600">확인 필요</span>
                  )}
                </p>
              </div>
              <div className="shrink-0 pl-3 text-right">
                <p className="font-semibold text-zinc-100">
                  {won(monthlyEquivalent(s))}
                  <span className="text-xs font-normal text-zinc-500">/월</span>
                </p>
                <p
                  className={`text-xs font-bold ${
                    d <= 3 ? "text-rose-400" : d <= 7 ? "text-amber-400" : "text-zinc-500"
                  }`}
                >
                  D-{d}
                </p>
              </div>
            </div>
          );
        })}
      </section>

      <Link
        href="/party"
        className="block rounded-2xl border border-sky-500/30 bg-sky-500/5 p-5 transition hover:bg-sky-500/10"
      >
        <p className="font-semibold text-sky-300">같이 쓸 사람 찾기</p>
        <p className="mt-1 text-sm text-zinc-400">
          쓰고 있는 구독을 N빵하면 매월 {won(Math.round(monthly * 0.6))}까지 줄일 수 있습니다.
        </p>
      </Link>
    </div>
  );
}
