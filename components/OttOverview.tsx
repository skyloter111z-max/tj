"use client";

import { monthlyEquivalent, type DetectedSubscription } from "@/lib/detector";
import { foundCount, ottStatuses } from "@/lib/ott";
import { iconFor } from "@/lib/service-icons";

const won = (n: number) => `${n.toLocaleString("ko-KR")}원`;

/**
 * 주요 OTT를 한눈에. 찾은 것은 금액과 함께, 못 찾은 것은 흐리게 보여 준다.
 * 못 찾았다고 안 쓰는 건 아니다 — 다른 카드나 앱스토어로 낼 수 있어 그 안내를 단다.
 */
export function OttOverview({
  subs,
  onOpen,
}: {
  subs: DetectedSubscription[];
  onOpen: (s: DetectedSubscription) => void;
}) {
  const statuses = ottStatuses(subs);
  const found = foundCount(statuses);

  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">주요 OTT</h2>
        <span className="text-xs text-zinc-500">
          {found > 0 ? `${found}개 구독 중` : "이 카드에선 못 찾음"}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2">
        {statuses.map(({ service, found }) =>
          found ? (
            <button
              type="button"
              key={service.id}
              onClick={() => onOpen(found)}
              className="flex items-center gap-2.5 rounded-xl border border-sky-500/30 bg-sky-500/5 px-3 py-3 text-left transition hover:bg-sky-500/10"
            >
              <span className="text-xl" aria-hidden>
                {iconFor(service.id)}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium text-zinc-100">{service.name}</span>
                <span className="block text-xs text-sky-300">{won(monthlyEquivalent(found))}/월</span>
              </span>
            </button>
          ) : (
            <div
              key={service.id}
              className="flex items-center gap-2.5 rounded-xl border border-zinc-800 px-3 py-3 opacity-50"
            >
              <span className="text-xl grayscale" aria-hidden>
                {iconFor(service.id)}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-sm text-zinc-400">{service.name}</span>
                <span className="block text-xs text-zinc-600">안 보여요</span>
              </span>
            </div>
          ),
        )}
      </div>

      <p className="text-xs leading-relaxed text-zinc-600">
        &apos;안 보여요&apos;가 안 쓴다는 뜻은 아닙니다. 다른 카드나 앱스토어로 결제하면 이 카드엔 안
        찍혀요. 아래에서 다른 카드·스토어도 확인해 보세요.
      </p>
    </section>
  );
}
