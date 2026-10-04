"use client";

import { nativeBridge } from "@/lib/card-alerts/bridge";

const openKakao = () => nativeBridge()?.openKakaoTalk?.();

/**
 * 카톡 카드사 알림방을 한 번 공유하면 몇 년치 결제를 읽어 구독을 찾는다.
 * 결제를 계속 지켜보지 않는다 — 새 결제를 반영하고 싶을 때만 다시 공유하면 된다.
 */
export function ImportHistoryCard() {
  return (
    <section className="space-y-4 rounded-2xl border border-yellow-400/30 bg-yellow-400/5 p-5">
      <div>
        <h2 className="text-base font-bold text-zinc-100">카톡 카드 알림방을 한 번만 공유해 주세요</h2>
        <p className="mt-1.5 text-xs leading-relaxed text-zinc-400">
          몇 년치 카드 결제를 한 번에 읽어 구독을 찾습니다. 한 번이면 끝이고, 새 결제를 반영하고 싶을 때만 다시
          공유하면 됩니다.
        </p>
      </div>
      <ol className="space-y-2 text-sm text-zinc-300">
        <li>
          <span className="mr-2 text-zinc-500">1</span>카톡에서 카드사 알림방(예: 삼성카드)을 엽니다
        </li>
        <li>
          <span className="mr-2 text-zinc-500">2</span>오른쪽 위 ≡ → ⚙ → 대화 내용 내보내기 → 텍스트만 보내기
        </li>
        <li>
          <span className="mr-2 text-zinc-500">3</span>공유 목록에서 <span className="font-semibold">구독모아</span>를
          고르면 끝
        </li>
      </ol>
      <button
        type="button"
        onClick={openKakao}
        className="w-full rounded-xl bg-yellow-400 px-4 py-3 font-bold text-yellow-950 transition hover:bg-yellow-300"
      >
        카카오톡 열기
      </button>
      <p className="text-center text-xs text-zinc-500">카드 결제 알림만 남기고, 나머지 대화는 저장하지 않습니다.</p>
    </section>
  );
}

/** 이미 가져온 사람: 새 결제를 반영하려면 다시 공유한다 */
export function ReimportLine({ span }: { span: string }) {
  return (
    <p className="text-center text-xs text-zinc-500">
      카톡에서 가져온 {span} 결제 기준 ·{" "}
      <button type="button" onClick={openKakao} className="font-semibold text-zinc-300 underline underline-offset-2">
        다시 가져오기
      </button>
    </p>
  );
}
