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

  // 캡처가 끝나고 앱으로 돌아왔을 때 온보딩이 아니라 홈이 뜨도록 표시해 둔다
  const markOnboarded = () => writeJSON(STORAGE_KEYS.onboarded, true);

  // 가장 확실한 길: 구글플레이 구독 화면 한 장. 로그인·카드알림·카톡 없이 누구나 바로 된다.
  const PLAY_URL = "https://play.google.com/store/account/subscriptions";
  const playOnce = () => {
    markOnboarded();
    if (canCapture) bridge?.startStoreCapture?.();
    else if (typeof window !== "undefined") window.open(PLAY_URL, "_blank", "noopener");
    onLaunch?.();
  };

  const start = () => {
    if (queue.length === 0) return;
    markOnboarded();
    if (canCapture) bridge?.startCaptureSequence?.(JSON.stringify(queue));
    else if (typeof window !== "undefined") window.open(queue[0]!.url, "_blank", "noopener");
    onLaunch?.();
  };

  return (
    <section className="space-y-4 rounded-2xl border border-zinc-800 bg-zinc-900/40 p-5">
      <div>
        <h2 className="text-sm font-bold text-zinc-100">{title}</h2>
        <p className="mt-1 text-xs leading-relaxed text-zinc-400">
          카드 알림도, 카톡도 필요 없어요. 구글플레이 구독 화면 한 장이면 앱으로 결제한 구독이 한 번에
          잡힙니다.
        </p>
      </div>

      <button
        type="button"
        onClick={playOnce}
        className="w-full rounded-xl bg-sky-500 px-4 py-3.5 text-center font-bold text-sky-950 transition hover:bg-sky-400"
      >
        구글플레이 구독 한 번에 찾기
      </button>

      <div className="flex items-center gap-3 pt-1">
        <span className="h-px flex-1 bg-zinc-800" />
        <span className="text-xs text-zinc-500">또는 원하는 것만 골라서</span>
        <span className="h-px flex-1 bg-zinc-800" />
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
        여러 개를 고르면 자동으로 다음 화면으로 넘어가기 위해 <span className="text-zinc-200">&apos;다른 앱
        위에 표시&apos;</span> 권한을 한 번 켜야 해요. 각 서비스에 <span className="text-zinc-200">로그인돼
        있어야</span> 금액이 보이고, 안 돼 있으면 그 화면은 건너뜁니다. 카드로 낸 구독은 카톡 가져오기로 더
        정확히 잡을 수 있어요.
      </p>
    </section>
  );
}
