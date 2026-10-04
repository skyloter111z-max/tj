import { findService } from "@/lib/merchants";
import { iconFor } from "@/lib/service-icons";

/** 알림 읽기를 막 허용해서 아직 구독이 확인되지 않은 상태 */
export function WatchingCard({ paymentCount }: { paymentCount: number }) {
  return (
    <div className="rounded-2xl border border-sky-500/30 bg-sky-500/5 p-6 text-center">
      <p className="text-3xl" aria-hidden>
        👀
      </p>
      <h1 className="mt-2 text-lg font-bold text-zinc-100">결제 알림을 지켜보고 있어요</h1>
      <p className="mt-1 text-sm text-zinc-400">
        지금까지 받은 카드 결제 알림 <span className="font-semibold text-zinc-200">{paymentCount}건</span>
      </p>
      <p className="mt-2 text-xs text-zinc-500">같은 곳에서 결제가 두 번 쌓이면 구독으로 확인합니다.</p>
    </div>
  );
}

/** 온보딩에서 고른 구독 — 결제 알림이 오기 전까지 "결제 대기"로 보여 준다 */
export function DeclaredWaiting({ declared }: { declared: Iterable<string> }) {
  const waiting = [...declared].map((id) => findService(id)).filter((s) => s !== undefined);
  if (waiting.length === 0) return null;

  return (
    <section className="rounded-2xl border border-zinc-800 bg-zinc-900/50 p-5">
      <h2 className="text-sm font-bold text-zinc-200">고르신 구독</h2>
      <p className="mt-1 text-xs text-zinc-500">다음 결제 알림이 오면 금액과 결제일을 확인해 드려요.</p>
      <ul className="mt-3 space-y-2">
        {waiting.map((s) => (
          <li key={s.id} className="flex items-center justify-between text-sm">
            <span className="flex items-center gap-2 text-zinc-200">
              <span aria-hidden>{iconFor(s.id)}</span>
              {s.name}
            </span>
            <span className="text-xs text-zinc-500">결제 대기</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
