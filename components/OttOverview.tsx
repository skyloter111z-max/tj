"use client";

import { nativeBridge } from "@/lib/card-alerts/bridge";
import { monthlyEquivalent, type DetectedSubscription } from "@/lib/detector";
import { foundCount, ottStatuses } from "@/lib/ott";
import type { ServiceDef } from "@/lib/merchants";
import { iconFor } from "@/lib/service-icons";

const won = (n: number) => `${n.toLocaleString("ko-KR")}원`;

/** 그 OTT의 구독 금액이 보이는 페이지. 없으면 해지 페이지로 대신한다 */
function readUrl(service: ServiceDef): string | undefined {
  return service.manageUrl ?? service.cancelUrl;
}

/**
 * 주요 OTT를 한눈에. 찾은 것은 금액과 함께, 못 찾은 것은 "눌러서 읽기"로 보여 준다.
 * 못 찾은 OTT도 눌러 그 서비스의 구독 화면을 열고 같은 방식(화면 캡처)으로 읽어 추가한다.
 * "모두 읽기"는 못 찾은 OTT들을 한 번의 동의로 차례로 열어 읽는다.
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
  const bridge = nativeBridge();
  const canCapture = typeof bridge?.startCaptureSequence === "function";

  // 한 서비스 화면을 연다: 앱이면 캡처로 읽고, 아니면 그 페이지를 새 탭으로 연다
  const read = (service: ServiceDef) => {
    const url = readUrl(service);
    if (!url) return;
    if (canCapture) bridge?.startCaptureSequence?.(JSON.stringify([{ id: service.id, url }]));
    else if (typeof window !== "undefined") window.open(url, "_blank", "noopener");
  };

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
            <button
              type="button"
              key={service.id}
              onClick={() => read(service)}
              disabled={!readUrl(service)}
              className="flex items-center gap-2.5 rounded-xl border border-zinc-800 px-3 py-3 text-left transition hover:border-zinc-700 hover:bg-zinc-800/40 disabled:pointer-events-none disabled:opacity-50"
            >
              <span className="text-xl grayscale" aria-hidden>
                {iconFor(service.id)}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-sm text-zinc-300">{service.name}</span>
                <span className="block text-xs text-zinc-500">
                  {canCapture ? "눌러서 읽기" : "눌러서 확인"}
                </span>
              </span>
            </button>
          ),
        )}
      </div>

      <p className="text-xs leading-relaxed text-zinc-600">
        &apos;눌러서 읽기&apos;를 누르면 그 OTT 화면을 열어 금액까지 읽어요. 여러 개를 한 번에 확인하려면
        아래 &apos;어떤 구독을 확인할까요?&apos;에서 골라 한 번에 읽을 수 있어요.
      </p>
    </section>
  );
}
