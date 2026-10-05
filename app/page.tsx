"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AutoCaptureOffer } from "@/components/AutoCapture";
import { SubscriptionDetail } from "@/components/SubscriptionDetail";
import { ImportHistoryCard, ReimportLine } from "@/components/ImportHistory";
import { MoreSources } from "@/components/MoreSources";
import { OttOverview } from "@/components/OttOverview";
import { DeclaredWaiting, WatchingCard } from "@/components/Watching";
import {
  bridgePlatform,
  kstDate,
  nativeBridge,
  readCapturedAlerts,
  readImportedAlerts,
  RESUME_EVENT,
} from "@/lib/card-alerts/bridge";
import { extractCardAlerts, type ImportResult } from "@/lib/card-alerts/import";
import { ingestPendingOcr, readStoreSubs } from "@/lib/store-subs/bridge";
import { mergeStoreSubs } from "@/lib/store-subs/parse";
import { exportSpan } from "@/lib/card-alerts/kakao-export";
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

const formatSpan = ({ from, to }: { from: string; to: string }) =>
  `${from.slice(0, 7).replace("-", ".")} ~ ${to.slice(0, 7).replace("-", ".")}`;

/**
 * sample: 브라우저. 결제 데이터가 없으니 샘플 거래로 엔진을 돌린다.
 * live:   앱. 안드로이드는 카톡 카드 알림방을 한 번 공유해 가져온 내역으로,
 *         아이폰은 단축어가 넘겨준 결제 문자로 판정한다.
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
      /** 카톡 공유를 받을 수 있는 앱(안드로이드) */
      canImport: boolean;
      /** 지금까지 카톡에서 가져온 기간 */
      importedSpan: { from: string; to: string } | null;
      /** 방금 카톡에서 가져왔다 */
      justImported: ImportResult | null;
      /** 안드로이드에서 알림 자동 수집이 아직 꺼져 있다 */
      autoCaptureOff: boolean;
      /** 방금 스토어 스크린샷에서 찾은 구독 수 (0이면 배너 안 띄움) */
      justOcr: number;
      /** 화면은 읽었는데 아는 구독을 못 찾았다 — 다시 시도 안내를 띄운다 */
      ocrReadNothing: boolean;
    };

function loadHome(): HomeState | "onboarding" {
  const bridge = nativeBridge();
  if (!bridge) {
    const subs = detectSubscriptions(SAMPLE_TRANSACTIONS, { today: SAMPLE_TODAY, knownKeys: KNOWN_KEYS });
    return { mode: "sample", today: SAMPLE_TODAY, subs: subs.filter((s) => s.active) };
  }

  // 카톡에서 공유받은 원본이 있으면 카드 결제 알림만 골라 저장한다. 원본은 앱이 이미 지웠다.
  // 처음 깐 사람이 바로 공유해도 온보딩 없이 결과부터 보여 준다.
  let justImported: ImportResult | null = null;
  const raw = bridge.takePendingExport?.() ?? "";
  if (raw) {
    justImported = extractCardAlerts(raw);
    bridge.saveImportedAlerts?.(JSON.stringify(justImported.alerts));
    writeJSON(STORAGE_KEYS.onboarded, true);
  }
  if (!readJSON(STORAGE_KEYS.onboarded, false)) return "onboarding";

  const today = kstDate(Date.now());
  const imported = readImportedAlerts(bridge);
  const seenBefore = readJSON<SeenMap>(STORAGE_KEYS.seen, {});
  const { seen, ...home } = buildLiveHome([imported, readCapturedAlerts(bridge)], today, seenBefore, {
    // 처음 가져온 몇 년치는 기준선이다 — 전부 "새로 찾은 구독"으로 띄우지 않는다
    baseline: justImported !== null && Object.keys(seenBefore).length === 0,
  });
  writeJSON(STORAGE_KEYS.seen, seen);

  // 스토어 스크린샷 OCR: 읽은 화면들의 글자가 있으면 파싱·저장하고, 저장된 스토어 구독을 합친다.
  // 각 화면엔 어느 서비스였는지(id)가 붙어 있어, "모두 읽기"의 OTT 화면도 그 서비스로 해석한다.
  const ocr = ingestPendingOcr(bridge);
  const storeSubs = readStoreSubs(bridge);
  const subsWithStore = mergeStoreSubs(home.subs, storeSubs, today);
  return {
    mode: "live",
    today,
    ...home,
    subs: subsWithStore,
    declared: readJSON<string[]>(STORAGE_KEYS.declared, []),
    canImport: bridgePlatform(bridge) === "android" && typeof bridge.openKakaoTalk === "function",
    importedSpan: exportSpan(imported),
    justImported,
    autoCaptureOff:
      bridgePlatform(bridge) === "android" &&
      !bridge.isAccessGranted() &&
      !readJSON(STORAGE_KEYS.autoCaptureDismissed, false),
    justOcr: ocr.found.length,
    ocrReadNothing: ocr.readText && ocr.found.length === 0,
  };
}

export default function HomePage() {
  const router = useRouter();
  const [home, setHome] = useState<HomeState | null>(null);
  const [autoCaptureHidden, setAutoCaptureHidden] = useState(false);
  const [selected, setSelected] = useState<DetectedSubscription | null>(null);

  // 브리지는 앱 WebView에서만 생긴다. 마운트 뒤에 읽고, 앱이 다시 앞으로 올 때마다 새로 읽는다.
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

  if (home.mode === "sample") {
    return (
      <div className="space-y-6">
        <Link
          href="/onboarding"
          className="block rounded-xl border border-zinc-800 bg-zinc-900/50 px-4 py-3 text-xs text-zinc-400 transition hover:text-zinc-200"
        >
          샘플 결제 내역으로 보여드리는 화면입니다. 구독모아 앱에서는 실제 카드 결제로 찾습니다 →
        </Link>
        <Subscriptions subs={home.subs} today={home.today} live={false} onOpen={setSelected} />
        <PartyLink subs={home.subs} />
        {selected && <SubscriptionDetail sub={selected} onClose={() => setSelected(null)} />}
      </div>
    );
  }

  const hasData = home.paymentCount > 0;

  return (
    <div className="space-y-6">
      {home.justImported && <ImportedBanner result={home.justImported} />}

      {home.justOcr > 0 && (
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-4 py-3 text-xs text-emerald-200/90">
          스크린샷에서 구독 {home.justOcr}개를 찾았어요
        </div>
      )}

      {home.justOcr === 0 && home.ocrReadNothing && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-xs text-amber-200/90">
          화면은 읽었지만 아는 구독을 못 찾았어요. 구독 화면이 다 보이게 한 뒤 다시 시도해 주세요.
        </div>
      )}

      {home.autoCaptureOff && !autoCaptureHidden && (home.importedSpan !== null || home.paymentCount > 0) && (
        <AutoCaptureOffer onDismiss={() => setAutoCaptureHidden(true)} />
      )}

      {home.subs.length > 0 ? (
        <Subscriptions subs={home.subs} today={home.today} live onOpen={setSelected} />
      ) : home.canImport && !home.importedSpan ? (
        <ImportHistoryCard />
      ) : home.importedSpan ? (
        <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-6 text-center">
          <p className="font-semibold text-zinc-200">가져온 결제에서 정기결제를 찾지 못했어요</p>
          <p className="mt-1 text-xs text-zinc-500">
            다른 카드를 쓰신다면 그 카드사 알림방도 공유해 주세요.
          </p>
        </div>
      ) : (
        <>
          <WatchingCard paymentCount={home.paymentCount} />
          <DeclaredWaiting declared={home.declared} />
        </>
      )}

      {home.importedSpan && !home.justImported && <ReimportLine span={formatSpan(home.importedSpan)} />}

      {home.ended > 0 && (
        <p className="text-center text-xs text-zinc-500">
          해지한 것으로 보이는 구독 {home.ended}개는 합계에서 뺐습니다
        </p>
      )}

      {hasData && <RecentPayments recent={home.recent} />}

      {home.importedSpan !== null && <MoreSources />}

      <PartyLink subs={home.subs} />

      {selected && <SubscriptionDetail sub={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function ImportedBanner({ result }: { result: ImportResult }) {
  if (result.alerts.length === 0) {
    return (
      <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-xs text-amber-200/80">
        공유하신 대화에서 카드 결제 알림을 찾지 못했어요. 카드사 알림방(예: 삼성카드)을 내보내 주세요.
      </div>
    );
  }
  return (
    <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-4 py-3 text-xs text-emerald-200/90">
      카톡에서 결제 {result.payments.toLocaleString("ko-KR")}건을 가져왔어요
      {result.span && <span className="text-emerald-200/60"> · {formatSpan(result.span)}</span>}
    </div>
  );
}

function PartyLink({ subs }: { subs: DetectedSubscription[] }) {
  if (subs.length === 0) return null;
  return (
    <Link
      href="/party"
      className="block rounded-2xl border border-sky-500/30 bg-sky-500/5 p-5 transition hover:bg-sky-500/10"
    >
      <p className="font-semibold text-sky-300">같이 쓸 사람 찾기</p>
      <p className="mt-1 text-sm text-zinc-400">
        쓰고 있는 구독을 N빵하면 매월 {won(Math.round(totalMonthly(subs) * 0.6))}까지 줄일 수 있습니다.
      </p>
    </Link>
  );
}

function Subscriptions({
  subs,
  today,
  live,
  onOpen,
}: {
  subs: DetectedSubscription[];
  today: string;
  live: boolean;
  onOpen: (s: DetectedSubscription) => void;
}) {
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

      {live && <OttOverview subs={subs} onOpen={onOpen} />}

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
            <button
              type="button"
              key={s.merchantNormalized}
              onClick={() => onOpen(s)}
              className="flex w-full items-center justify-between rounded-xl border border-zinc-800 bg-zinc-900/40 px-4 py-3 text-left transition hover:bg-zinc-900/80"
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
            </button>
          );
        })}
      </section>
    </>
  );
}

/** 가져온 결제 중 최근 것 — 무엇을 읽었는지 사용자가 바로 확인한다 */
function RecentPayments({ recent }: { recent: RawTransaction[] }) {
  return (
    <section className="space-y-3">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">최근 결제</h2>
      {recent.length === 0 ? (
        <p className="rounded-xl border border-zinc-800 bg-zinc-900/40 px-4 py-3 text-sm text-zinc-500">
          아직 읽은 결제가 없어요.
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
