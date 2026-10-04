"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { DeclaredWaiting, WatchingCard } from "@/components/Watching";
import {
  bridgePlatform,
  kstDate,
  nativeBridge,
  readCapturedAlerts,
  RESUME_EVENT,
} from "@/lib/card-alerts/bridge";
import {
  daysUntilCharge,
  detectSubscriptions,
  monthlyEquivalent,
  totalMonthly,
  type DetectedSubscription,
  type RawTransaction,
} from "@/lib/detector";
import { buildLiveHome, type SeenMap } from "@/lib/home";
import { KNOWN_KEYS, SAMPLE_TRANSACTIONS } from "@/lib/sample-data";
import { readJSON, STORAGE_KEYS, writeJSON } from "@/lib/storage";

const won = (n: number) => `${n.toLocaleString("ko-KR")}원`;
const SAMPLE_TODAY = "2026-10-03";

const CYCLE_LABEL = { weekly: "주", monthly: "월", yearly: "연" } as const;

/**
 * sample: 브라우저. 앱이 아니라 결제 알림이 없으니 샘플 거래로 엔진을 돌린다.
 * live:   안드로이드·아이폰 앱. 브리지로 받은 실제 결제 알림으로 판정한다.
 */
type HomeState =
  | { mode: "sample"; today: string; subs: DetectedSubscription[] }
  | {
      mode: "live";
      today: string;
      subs: DetectedSubscription[];
      ended: number;
      recent: RawTransaction[];
      paymentCount: number;
      declared: string[];
      /** 안드로이드에서 알림 접근이 꺼졌다 — 새 결제를 못 읽는 중 */
      accessOff: boolean;
    };

function loadHome(): HomeState | "onboarding" {
  const bridge = nativeBridge();
  if (!bridge) {
    const subs = detectSubscriptions(SAMPLE_TRANSACTIONS, { today: SAMPLE_TODAY, knownKeys: KNOWN_KEYS });
    return { mode: "sample", today: SAMPLE_TODAY, subs: subs.filter((s) => s.active) };
  }
  if (!readJSON(STORAGE_KEYS.onboarded, false)) return "onboarding";

  const today = kstDate(Date.now());
  const { seen, ...home } = buildLiveHome(
    readCapturedAlerts(bridge),
    today,
    readJSON<SeenMap>(STORAGE_KEYS.seen, {}),
  );
  writeJSON(STORAGE_KEYS.seen, seen);
  return {
    mode: "live",
    today,
    ...home,
    declared: readJSON<string[]>(STORAGE_KEYS.declared, []),
    accessOff: bridgePlatform(bridge) === "android" && !bridge.isAccessGranted(),
  };
}

export default function HomePage() {
  const router = useRouter();
  const [home, setHome] = useState<HomeState | null>(null);

  // 브리지는 앱 WebView에서만 생긴다. 마운트 뒤에 읽고, 앱이 다시 앞으로 올 때마다 새로 읽는다
  // — 결제하고 돌아오면 방금 온 알림이 바로 보여야 한다.
  useEffect(() => {
    const load = () => {
      const next = loadHome();
      if (next === "onboarding") router.replace("/onboarding");
      else setHome(next);
    };
    load();
    window.addEventListener(RESUME_EVENT, load);
    return () => window.removeEventListener(RESUME_EVENT, load);
  }, [router]);

  if (!home) {
    return <div className="h-32 animate-pulse rounded-2xl bg-zinc-900/60" aria-label="불러오는 중" />;
  }

  const live = home.mode === "live";

  return (
    <div className="space-y-6">
      {home.mode === "sample" && (
        <Link
          href="/onboarding"
          className="block rounded-xl border border-zinc-800 bg-zinc-900/50 px-4 py-3 text-xs text-zinc-400 transition hover:text-zinc-200"
        >
          샘플 결제 내역으로 보여드리는 화면입니다. 구독모아 앱에서는 실제 결제 알림으로 찾습니다 →
        </Link>
      )}

      {live && home.accessOff && <AccessOffBanner />}

      {live && home.subs.length === 0 ? (
        <>
          <WatchingCard paymentCount={home.paymentCount} />
          <DeclaredWaiting declared={home.declared} />
        </>
      ) : (
        <Subscriptions subs={home.subs} today={home.today} live={live} />
      )}

      {live && home.ended > 0 && (
        <p className="text-center text-xs text-zinc-500">
          해지한 것으로 보이는 구독 {home.ended}개는 합계에서 뺐습니다
        </p>
      )}

      {live && <RecentPayments recent={home.recent} />}

      {home.subs.length > 0 && (
        <Link
          href="/party"
          className="block rounded-2xl border border-sky-500/30 bg-sky-500/5 p-5 transition hover:bg-sky-500/10"
        >
          <p className="font-semibold text-sky-300">같이 쓸 사람 찾기</p>
          <p className="mt-1 text-sm text-zinc-400">
            쓰고 있는 구독을 N빵하면 매월 {won(Math.round(totalMonthly(home.subs) * 0.6))}까지 줄일 수 있습니다.
          </p>
        </Link>
      )}
    </div>
  );
}

function Subscriptions({ subs, today, live }: { subs: DetectedSubscription[]; today: string; live: boolean }) {
  const monthly = totalMonthly(subs);
  const newSubs = subs.filter((s) => s.isNew);
  const upcoming = [...subs].sort((a, b) => daysUntilCharge(a, today) - daysUntilCharge(b, today));

  return (
    <>
      <section className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-6">
        <p className="text-xs font-medium text-zinc-500">이번 달 구독 지출</p>
        <p className="mt-1 text-3xl font-bold tracking-tight text-zinc-50">{won(monthly)}</p>
        <p className="mt-1 text-sm text-zinc-400">
          구독 {subs.length}개 · 연 {won(monthly * 12)}
        </p>
      </section>

      {newSubs.length > 0 && (
        <section className="rounded-2xl border border-amber-500/30 bg-amber-500/5 p-5">
          <h2 className="text-sm font-bold text-amber-300">
            {live ? "새로 찾은" : "새로 생긴"} 정기결제 {newSubs.length}개
          </h2>
          <p className="mt-1 text-xs text-amber-200/70">
            {live
              ? "처음 확인된 구독입니다. 무료 체험이 유료로 바뀐 건 아닌지 확인해 보세요."
              : "무료 체험이 유료로 바뀐 것일 수 있습니다."}
          </p>
          <ul className="mt-3 space-y-1.5">
            {newSubs.map((s) => (
              <li key={s.merchantNormalized} className="flex justify-between text-sm">
                <span className="text-zinc-200">{s.displayName}</span>
                <span className="font-semibold text-zinc-100">
                  {won(s.amount)}/{CYCLE_LABEL[s.cycle]}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="space-y-3">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">결제 예정</h2>
        {upcoming.map((s) => {
          const d = daysUntilCharge(s, today);
          return (
            <div
              key={s.merchantNormalized}
              className="flex items-center justify-between rounded-xl border border-zinc-800 bg-zinc-900/40 px-4 py-3"
            >
              <div className="min-w-0">
                <p className="truncate font-medium text-zinc-100">{s.displayName}</p>
                <p className="mt-0.5 text-xs text-zinc-500">
                  {s.nextChargeDate}
                  {s.priceChange && (
                    <span className="ml-2 text-amber-400">
                      {won(s.priceChange.from)} → {won(s.priceChange.to)}
                    </span>
                  )}
                  {s.confidence < 0.6 && <span className="ml-2 text-zinc-600">확인 필요</span>}
                </p>
              </div>
              <div className="shrink-0 pl-3 text-right">
                <p className="font-semibold text-zinc-100">
                  {won(monthlyEquivalent(s))}
                  <span className="text-xs font-normal text-zinc-500">/월</span>
                </p>
                <p
                  className={`text-xs font-bold ${
                    d < 0 ? "text-zinc-500" : d <= 3 ? "text-rose-400" : d <= 7 ? "text-amber-400" : "text-zinc-500"
                  }`}
                >
                  {/* 결제일이 지났는데 알림이 아직 없다 — 늦게 오거나 해지했을 수 있다 */}
                  {d < 0 ? "결제 확인 중" : `D-${d}`}
                </p>
              </div>
            </div>
          );
        })}
      </section>
    </>
  );
}

/** 결제하고 앱을 열면 여기서 바로 보인다 — 알림 읽기가 동작한다는 확인이다 */
function RecentPayments({ recent }: { recent: RawTransaction[] }) {
  return (
    <section className="space-y-3">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">최근 받은 결제 알림</h2>
      {recent.length === 0 ? (
        <p className="rounded-xl border border-zinc-800 bg-zinc-900/40 px-4 py-3 text-sm text-zinc-500">
          아직 받은 결제 알림이 없어요. 카드로 결제하면 여기에 바로 나타납니다.
        </p>
      ) : (
        <ul className="divide-y divide-zinc-800 rounded-xl border border-zinc-800 bg-zinc-900/40">
          {recent.map((t, i) => (
            <li key={`${t.date}-${t.merchantRaw}-${i}`} className="flex items-center justify-between px-4 py-2.5 text-sm">
              <span className="min-w-0 truncate text-zinc-200">{t.merchantRaw}</span>
              <span className="shrink-0 pl-3 text-right">
                <span className="font-medium text-zinc-100">{won(t.amount)}</span>
                <span className="ml-2 text-xs text-zinc-500">{t.date.slice(5).replace("-", "/")}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function AccessOffBanner() {
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3">
      <p className="text-xs text-amber-200/80">알림 접근이 꺼져 있어서 새 결제를 읽지 못하고 있어요.</p>
      <button
        type="button"
        onClick={() => nativeBridge()?.openAccessSettings()}
        className="shrink-0 rounded-lg bg-amber-400 px-3 py-1.5 text-xs font-bold text-amber-950"
      >
        다시 켜기
      </button>
    </div>
  );
}
