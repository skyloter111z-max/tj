"use client";

import { nativeBridge } from "@/lib/card-alerts/bridge";

/**
 * 가져온 카드에서 구독이 적게 나왔을 때, 왜 그런지와 다음 행동을 안내한다.
 * 구독은 보통 여러 카드·앱스토어에 흩어져 있어서, 한 카드만 보면 일부만 잡힌다.
 */
export function MoreSources() {
  const openStore = (url: string) => {
    // 앱이면 브리지로 외부 열기, 웹이면 새 탭
    if (typeof window !== "undefined") window.open(url, "_blank", "noopener");
  };

  return (
    <section className="space-y-3 rounded-2xl border border-zinc-800 bg-zinc-900/40 p-5">
      <div>
        <h2 className="text-sm font-bold text-zinc-200">구독이 더 있을 수 있어요</h2>
        <p className="mt-1 text-xs leading-relaxed text-zinc-500">
          구독은 카드마다, 앱스토어마다 흩어져 있습니다. 아래를 더 확인하면 놓친 구독을 찾습니다.
        </p>
      </div>
      <div className="space-y-2">
        <button
          type="button"
          onClick={() => nativeBridge()?.openKakaoTalk?.()}
          className="flex w-full items-center justify-between rounded-lg border border-zinc-800 px-4 py-2.5 text-sm text-zinc-200 transition hover:bg-zinc-800"
        >
          <span>다른 카드사 알림방도 공유하기</span>
          <span aria-hidden className="text-zinc-600">›</span>
        </button>
        <button
          type="button"
          onClick={() => openStore("https://play.google.com/store/account/subscriptions")}
          className="flex w-full items-center justify-between rounded-lg border border-zinc-800 px-4 py-2.5 text-sm text-zinc-200 transition hover:bg-zinc-800"
        >
          <span>구글플레이 구독 확인하기</span>
          <span aria-hidden className="text-zinc-600">›</span>
        </button>
        <button
          type="button"
          onClick={() => openStore("https://apps.apple.com/account/subscriptions")}
          className="flex w-full items-center justify-between rounded-lg border border-zinc-800 px-4 py-2.5 text-sm text-zinc-200 transition hover:bg-zinc-800"
        >
          <span>앱스토어 구독 확인하기</span>
          <span aria-hidden className="text-zinc-600">›</span>
        </button>
      </div>
      <p className="rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-2.5 text-xs leading-relaxed text-zinc-400">
        넷플릭스·유튜브처럼 <span className="text-zinc-200">앱스토어로 결제</span>한 구독은 카드에 서비스명이
        안 찍혀요. 위 버튼으로 스토어 구독 화면을 연 뒤 <span className="text-zinc-200">화면을 캡처해서
        구독모아로 공유</span>하면, 글자를 읽어 자동으로 추가합니다.
      </p>
    </section>
  );
}
