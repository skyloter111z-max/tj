"use client";

import Link from "next/link";
import { monthlyEquivalent, type DetectedSubscription } from "@/lib/detector";
import { iconFor } from "@/lib/service-icons";
import { partyForService, savingsPerMonth } from "@/lib/parties";

const won = (n: number) => `${n.toLocaleString("ko-KR")}원`;
const CYCLE_LABEL = { weekly: "매주", monthly: "매월", yearly: "매년" } as const;
const ym = (d: string) => `${d.slice(0, 4)}.${d.slice(5, 7)}`;

/** 구독 하나를 눌렀을 때: 그동안 쓴 총액 + 해지 방법 + 같이 쓰기 */
export function SubscriptionDetail({ sub, onClose }: { sub: DetectedSubscription; onClose: () => void }) {
  const party = sub.service ? partyForService(sub.service.id) : null;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-4" onClick={onClose}>
      <div
        className="w-full max-w-md space-y-5 rounded-2xl border border-zinc-700 bg-zinc-900 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3">
          <span className="text-2xl" aria-hidden>
            {sub.service ? iconFor(sub.service.id) : "💳"}
          </span>
          <div className="min-w-0">
            <p className="truncate text-lg font-bold text-zinc-100">{sub.displayName}</p>
            <p className="text-sm text-zinc-400">
              {CYCLE_LABEL[sub.cycle]} {won(sub.amount)}
              {!sub.active && <span className="ml-2 text-zinc-500">· 해지한 것 같아요</span>}
            </p>
          </div>
        </div>

        {/* 가져온 내역이 주는 한 방: 그동안 얼마 썼는지 */}
        <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-4 text-center">
          <p className="text-xs text-zinc-500">그동안 이 구독에 쓴 돈</p>
          <p className="mt-1 text-2xl font-bold text-zinc-50">{won(sub.totalPaid)}</p>
          <p className="mt-1 text-xs text-zinc-500">
            {ym(sub.firstChargeDate)}부터 {sub.occurrences}번 결제
          </p>
        </div>

        <dl className="space-y-2 text-sm">
          {sub.active && (
            <div className="flex justify-between">
              <dt className="text-zinc-500">다음 결제</dt>
              <dd className="text-zinc-200">{sub.nextChargeDate}</dd>
            </div>
          )}
          {sub.priceChange && (
            <div className="flex justify-between">
              <dt className="text-zinc-500">가격 변동</dt>
              <dd className="text-amber-400">
                {won(sub.priceChange.from)} → {won(sub.priceChange.to)}
              </dd>
            </div>
          )}
          <div className="flex justify-between">
            <dt className="text-zinc-500">1년이면</dt>
            <dd className="text-zinc-200">{won(monthlyEquivalent(sub) * 12)}</dd>
          </div>
        </dl>

        <div className="space-y-2">
          {party && sub.active && (
            <Link
              href={`/party/${party.id}`}
              className="block w-full rounded-xl bg-sky-500 px-4 py-3 text-center font-bold text-sky-950 transition hover:bg-sky-400"
            >
              같이 쓰고 매월 {won(savingsPerMonth(party))} 아끼기
            </Link>
          )}
          {sub.service?.cancelUrl && (
            <a
              href={sub.service.cancelUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="block w-full rounded-xl border border-zinc-700 px-4 py-3 text-center font-semibold text-zinc-200 transition hover:bg-zinc-800"
            >
              해지 방법 보기
            </a>
          )}
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
