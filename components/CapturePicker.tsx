"use client";

import { useState } from "react";
import { nativeBridge } from "@/lib/card-alerts/bridge";
import { buildQueue, captureGroups, defaultSelection } from "@/lib/capture-targets";
import { STORAGE_KEYS, writeJSON } from "@/lib/storage";

/**
 * "어떤 구독을 확인할까요?" — 고른 서비스의 구독 화면을 한 번의 동의로 차례로 열어 읽는다.
 *
 * 카톡(카드 알림)으로 시작하지 않아도 되는 길이다. 안드로이드 앱에서는 화면 캡처로 자동 확인하고,
 * 그 밖(웹 미리보기)에서는 첫 화면만 새 탭으로 연다.
 */
export function CapturePicker({
  title = "어떤 구독을 확인할까요?",
  onLaunch,
}: {
  title?: string;
  onLaunch?: () => void;
}) {
  const bridge = nativeBridge();
  const canCapture = typeof bridge?.startCaptureSequence === "function";
  const groups = captureGroups();
  const [selected, setSelected] = useState<Set<string>>(() => defaultSelection());

  const toggle = (key: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const queue = buildQueue(selected);

  const start = () => {
    if (queue.length === 0) return;
    // 캡처가 끝나고 앱으로 돌아왔을 때 온보딩이 아니라 홈이 뜨도록 표시해 둔다
    writeJSON(STORAGE_KEYS.onboarded, true);
    if (canCapture) bridge?.startCaptureSequence?.(JSON.stringify(queue));
    else if (typeof window !== "undefined") window.open(queue[0]!.url, "_blank", "noopener");
    onLaunch?.();
  };

  return (
    <section className="space-y-4 rounded-2xl border border-zinc-800 bg-zinc-900/40 p-5">
      <div>
        <h2 className="text-sm font-bold text-zinc-100">{title}</h2>
        <p className="mt-1 text-xs leading-relaxed text-zinc-400">
          고른 구독 화면을 차례로 열어 금액까지 읽어요. 화면 캡처 동의는 한 번이면 됩니다.
        </p>
      </div>

      {groups.map((group) => (
        <div key={group.label} className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">{group.label}</h3>
          <div className="grid grid-cols-4 gap-2">
            {group.targets.map((t) => {
              const on = selected.has(t.key);
              return (
                <button
                  key={t.key}
                  type="button"
                  onClick={() => toggle(t.key)}
                  aria-pressed={on}
                  className={`flex min-h-[78px] flex-col items-center justify-start gap-1.5 rounded-xl border-2 px-1 py-2.5 transition ${
                    on ? "border-sky-400 bg-sky-400/10" : "border-zinc-800 bg-zinc-900/50 hover:border-zinc-700"
                  }`}
                >
                  <span aria-hidden className="text-2xl leading-none">
                    {t.icon}
                  </span>
                  <span
                    className={`line-clamp-2 w-full px-0.5 text-center text-[11px] leading-tight ${
                      on ? "font-semibold text-sky-200" : "text-zinc-400"
                    }`}
                  >
                    {t.name}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      ))}

      <button
        type="button"
        onClick={start}
        disabled={queue.length === 0}
        className="w-full rounded-xl bg-sky-500 px-4 py-3.5 text-center font-bold text-sky-950 transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:bg-zinc-800 disabled:text-zinc-500"
      >
        {queue.length > 0 ? `선택한 ${queue.length}개 확인하기` : "확인할 구독을 골라주세요"}
      </button>

      {!canCapture && (
        <p className="text-center text-xs text-zinc-500">
          화면 캡처 자동 확인은 안드로이드 앱에서 됩니다. 여기선 첫 화면만 열려요.
        </p>
      )}
      <p className="rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-2.5 text-xs leading-relaxed text-zinc-400">
        각 서비스에 <span className="text-zinc-200">로그인돼 있어야</span> 금액이 보여요. 안 돼 있으면 그
        화면은 건너뜁니다. 카드로 낸 구독은 카톡 가져오기로 더 정확히 잡을 수 있어요.
      </p>
    </section>
  );
}
