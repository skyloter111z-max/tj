"use client";

import { useState } from "react";
import { nativeBridge } from "@/lib/card-alerts/bridge";
import { STORAGE_KEYS, writeJSON } from "@/lib/storage";

/**
 * 가져오기(과거)를 마친 뒤 "앞으로 오는 결제도 자동으로" 권한을 제안한다.
 *
 * 알림 리스너는 카톡 알림톡·카드사 앱 푸시가 뜨는 순간 읽으므로, 사용자가 카드를 문자로 바꿀
 * 필요가 없다. 모든 알림을 받되 AlertFilter가 카드 결제 알림만 남기고 나머지는 즉시 버린다 —
 * 안심 문구는 이 사실만 적는다("읽지 않는다"는 과장이다).
 *
 * 안드로이드 설정 화면은 차갑게 느껴지므로, 넘어가기 직전에 "스위치를 켜주세요" 안내를 먼저 띄운다.
 */
export function AutoCaptureOffer({ onDismiss }: { onDismiss: () => void }) {
  const [showHint, setShowHint] = useState(false);

  const dismiss = () => {
    writeJSON(STORAGE_KEYS.autoCaptureDismissed, true);
    onDismiss();
  };

  return (
    <section className="space-y-4 rounded-2xl border border-sky-500/30 bg-sky-500/5 p-5">
      <div>
        <h2 className="text-base font-bold text-zinc-100">앞으로 결제될 구독도 알아서 기록할까요?</h2>
        <p className="mt-1.5 text-xs leading-relaxed text-zinc-400">
          권한을 허용하시면 매번 카톡 내역을 공유할 필요 없이, 새로운 구독 결제를 자동으로 찾아드려요.
        </p>
      </div>
      <p className="rounded-lg border border-zinc-800 bg-zinc-900/50 px-3 py-2.5 text-xs leading-relaxed text-zinc-500">
        🔒 카드사 결제 알림톡과 앱 푸시에서 <span className="text-zinc-300">카드 결제 내역만</span> 남기고,
        개인 대화 등 나머지 알림은 그 즉시 버립니다. 폰 안에서만 처리하고 서버로 보내지 않습니다.
      </p>
      <div className="space-y-2">
        <button
          type="button"
          onClick={() => setShowHint(true)}
          className="w-full rounded-xl bg-sky-500 px-4 py-3 font-bold text-sky-950 transition hover:bg-sky-400"
        >
          알림 권한 허용하고 자동화하기
        </button>
        <button
          type="button"
          onClick={dismiss}
          className="w-full py-2 text-sm text-zinc-500 transition hover:text-zinc-300"
        >
          나중에 수동으로 할게요
        </button>
      </div>

      {showHint && <PermissionHint onOpen={() => nativeBridge()?.openAccessSettings?.()} onClose={() => setShowHint(false)} />}
    </section>
  );
}

/** 설정 화면으로 넘어가기 직전 안내. 어느 스위치를 켜야 하는지 먼저 보여 준다 */
function PermissionHint({ onOpen, onClose }: { onOpen: () => void; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-4" onClick={onClose}>
      <div
        className="w-full max-w-md space-y-4 rounded-2xl border border-zinc-700 bg-zinc-900 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div>
          <p className="text-base font-bold text-zinc-100">다음 화면에서 한 번만</p>
          <p className="mt-1.5 text-sm leading-relaxed text-zinc-400">
            설정 → 알림 접근 목록에서 <span className="font-semibold text-sky-300">구독모아</span> 스위치를 켜고
            돌아오면 됩니다.
          </p>
        </div>
        <div className="flex items-center gap-3 rounded-xl border border-zinc-800 bg-zinc-950 px-4 py-3">
          <span className="text-sm text-zinc-200">구독모아</span>
          <span className="ml-auto flex h-6 w-11 items-center rounded-full bg-sky-500 px-0.5">
            <span className="ml-auto h-5 w-5 rounded-full bg-white" />
          </span>
        </div>
        <div className="space-y-2">
          <button
            type="button"
            onClick={() => {
              onClose();
              onOpen();
            }}
            className="w-full rounded-xl bg-sky-500 px-4 py-3 font-bold text-sky-950 transition hover:bg-sky-400"
          >
            설정 열기
          </button>
          <button
            type="button"
            onClick={onClose}
            className="w-full py-2 text-sm text-zinc-500 transition hover:text-zinc-300"
          >
            닫기
          </button>
        </div>
      </div>
    </div>
  );
}
