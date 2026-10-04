"use client";

import { nativeBridge } from "@/lib/card-alerts/bridge";

/**
 * 카톡 카드사 알림방을 내보내 구독모아로 공유하면, 몇 년치 결제를 한 번에 읽는다(선택).
 * 알림 읽기만으로는 허용한 뒤의 결제만 잡히므로, 구독을 바로 보고 싶은 사람을 위한 길이다.
 */
export function ImportHistoryCard() {
  return (
    <section className="space-y-3 rounded-2xl border border-zinc-800 bg-zinc-900/50 p-5">
      <div>
        <h2 className="text-sm font-bold text-zinc-200">지난 결제도 가져오기 (선택)</h2>
        <p className="mt-1 text-xs leading-relaxed text-zinc-500">
          카톡 카드사 알림방을 내보내면 몇 년치 결제를 한 번에 읽어 바로 구독을 찾습니다. 카드 결제 알림만
          남기고 나머지는 저장하지 않습니다.
        </p>
      </div>
      <ol className="space-y-1 text-xs text-zinc-400">
        <li>1. 카톡에서 카드사 알림방(예: 삼성카드)을 엽니다</li>
        <li>2. 오른쪽 위 ≡ → ⚙ → 대화 내용 내보내기 → 텍스트만 보내기</li>
        <li>3. 공유 목록에서 구독모아를 고르면 끝</li>
      </ol>
      <button
        type="button"
        onClick={() => nativeBridge()?.openKakaoTalk?.()}
        className="w-full rounded-lg bg-yellow-400 px-3 py-2.5 text-sm font-bold text-yellow-950 transition hover:bg-yellow-300"
      >
        카카오톡 열기
      </button>
    </section>
  );
}
