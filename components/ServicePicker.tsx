"use client";

import { CATEGORY_LABELS, iconFor, servicesByCategory } from "@/lib/service-icons";

/**
 * 온보딩 0단계 — "어떤 구독을 쓰고 계신가요?"
 *
 * 선택은 **힌트이지 필터가 아니다**(spec/v5 §3.1.1). 고르지 않은 구독도 스캔에서
 * 계속 찾는다. 그래서 화면 문구도 "기억나는 것만"이라고 말하고, 전부 고르라고
 * 압박하지 않는다.
 */
export function ServicePicker({
  selected,
  onToggle,
}: {
  selected: ReadonlySet<string>;
  onToggle: (id: string) => void;
}) {
  return (
    <div className="space-y-6">
      {servicesByCategory().map(({ category, services }) => (
        <section key={category}>
          <h3 className="mb-2.5 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            {CATEGORY_LABELS[category]}
          </h3>
          <div className="grid grid-cols-4 gap-2.5">
            {services.map((s) => {
              const on = selected.has(s.id);
              return (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => onToggle(s.id)}
                  aria-pressed={on}
                  className={`flex min-h-[86px] flex-col items-center justify-start gap-1.5 rounded-xl border-2 px-1 py-3 transition ${
                    on
                      ? "border-sky-400 bg-sky-400/10"
                      : "border-zinc-800 bg-zinc-900/50 hover:border-zinc-700"
                  }`}
                >
                  <span aria-hidden className="text-2xl leading-none">
                    {iconFor(s.id)}
                  </span>
                  <span
                    className={`line-clamp-2 w-full px-0.5 text-center text-[11px] leading-tight ${
                      on ? "font-semibold text-sky-200" : "text-zinc-400"
                    }`}
                  >
                    {s.name}
                  </span>
                </button>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
