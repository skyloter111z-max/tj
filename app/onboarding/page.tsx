"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ServicePicker } from "@/components/ServicePicker";
import { DeclaredWaiting, WatchingCard } from "@/components/Watching";
import {
  bridgePlatform,
  kstDate,
  nativeBridge,
  readCapturedAlerts,
  RESUME_EVENT,
  type NativeBridge,
} from "@/lib/card-alerts/bridge";
import { collectTransactions } from "@/lib/card-alerts/parse";
import { detectSubscriptions, monthlyEquivalent, totalMonthly } from "@/lib/detector";
import { iconFor } from "@/lib/service-icons";
import { SAMPLE_TRANSACTIONS } from "@/lib/sample-data";
import { readJSON, STORAGE_KEYS, writeJSON } from "@/lib/storage";

const won = (n: number) => `${n.toLocaleString("ko-KR")}원`;
const SAMPLE_TODAY = "2026-10-04";

type Step = "services" | "connect" | "result";

/** live: 안드로이드 앱이 모은 실제 결제 알림 / sample: 브라우저·아이폰에서 보는 미리보기 */
type Mode = "live" | "sample";

export default function OnboardingPage() {
  const [step, setStep] = useState<Step>("services");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [mode, setMode] = useState<Mode>("sample");
  // 브리지는 앱 WebView에서만 생긴다. 서버 렌더와 어긋나지 않게 마운트 뒤에 읽는다.
  const [bridge, setBridge] = useState<NativeBridge | null>(null);
  useEffect(() => setBridge(nativeBridge()), []);

  // 선택은 기기에만 남는다. 저장이 막힌 환경(시크릿 모드 등)에서도 동작해야 한다.
  useEffect(() => {
    setSelected(new Set(readJSON<string[]>(STORAGE_KEYS.declared, [])));
  }, []);

  function persist(next: Set<string>) {
    // 선언은 힌트일 뿐이라 저장이 안 돼도 판정은 된다
    writeJSON(STORAGE_KEYS.declared, [...next]);
  }

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      persist(next);
      return next;
    });
  }

  return (
    <div className="space-y-6">
      <StepDots step={step} />

      {step === "services" && (
        <ServicesStep
          selected={selected}
          onToggle={toggle}
          onNext={() => setStep("connect")}
        />
      )}

      {step === "connect" && (
        <ConnectStep
          bridge={bridge}
          onBack={() => setStep("services")}
          onGranted={() => {
            setMode("live");
            setStep("result");
          }}
          onPreview={() => {
            setMode("sample");
            setStep("result");
          }}
        />
      )}

      {step === "result" && <ResultStep declared={selected} mode={mode} bridge={bridge} />}
    </div>
  );
}

function StepDots({ step }: { step: Step }) {
  const order: Step[] = ["services", "connect", "result"];
  const idx = order.indexOf(step);
  return (
    <div className="flex gap-1.5" aria-label={`${idx + 1} / ${order.length} 단계`}>
      {order.map((s, i) => (
        <span
          key={s}
          className={`h-1 flex-1 rounded-full transition-colors ${
            i <= idx ? "bg-sky-400" : "bg-zinc-800"
          }`}
        />
      ))}
    </div>
  );
}

function ServicesStep({
  selected,
  onToggle,
  onNext,
}: {
  selected: Set<string>;
  onToggle: (id: string) => void;
  onNext: () => void;
}) {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-zinc-100">어떤 구독을 쓰고 계신가요?</h1>
        <p className="mt-1.5 text-sm leading-relaxed text-zinc-400">
          기억나는 것만 골라주세요. <span className="text-zinc-300">나머지는 저희가 찾습니다.</span>
        </p>
      </div>

      <ServicePicker selected={selected} onToggle={onToggle} />

      {/* 고정 바가 마지막 카테고리를 가리지 않도록 그만큼 비워 둔다 */}
      <div aria-hidden className="h-28" />

      {/* 배경을 깔지 않으면 뒤 카드가 비쳐 글자가 겹친다 */}
      <div className="fixed inset-x-0 bottom-0 border-t border-zinc-800 bg-zinc-950/95 backdrop-blur">
        <div className="mx-auto max-w-2xl space-y-2 px-4 pb-4 pt-3">
          <button
            type="button"
            onClick={onNext}
            className="w-full rounded-xl bg-sky-500 px-4 py-3.5 font-bold text-sky-950 transition hover:bg-sky-400"
          >
            {selected.size > 0 ? `${selected.size}개 선택하고 계속` : "건너뛰고 계속"}
          </button>
          <p className="text-center text-xs text-zinc-500">
            고르지 않아도 됩니다. 빠뜨린 구독을 찾는 게 이 앱이 하는 일입니다.
          </p>
        </div>
      </div>
    </div>
  );
}

function ConnectStep({
  bridge,
  onBack,
  onGranted,
  onPreview,
}: {
  bridge: NativeBridge | null;
  onBack: () => void;
  onGranted: () => void;
  onPreview: () => void;
}) {
  // 설정 화면에서 토글을 켜고 돌아오면 앱이 RESUME_EVENT를 쏜다. 그때 다시 확인한다.
  useEffect(() => {
    if (!bridge) return;
    const check = () => {
      if (bridge.isAccessGranted()) onGranted();
    };
    window.addEventListener(RESUME_EVENT, check);
    return () => window.removeEventListener(RESUME_EVENT, check);
  }, [bridge, onGranted]);

  if (bridge && bridgePlatform(bridge) === "ios") {
    return <IosConnect bridge={bridge} onBack={onBack} onDone={onGranted} />;
  }

  const granted = bridge?.isAccessGranted() ?? false;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-zinc-100">카드 결제 알림을 읽게 해 주세요</h1>
        <p className="mt-1.5 text-sm text-zinc-400">
          허용 한 번이면 끝입니다. 결제 알림이 올 때마다 저절로 구독을 찾습니다.
        </p>
      </div>

      <Steps
        items={[
          ["알림 접근 허용", "아래 버튼을 누르면 설정 화면이 열립니다"],
          ["구독모아 켜기", "목록에서 구독모아를 켜고 돌아오면 됩니다"],
          ["끝", "카톡·문자·카드사 앱으로 오는 결제 알림을 알아서 읽습니다"],
        ]}
      />

      <PrivacyNote
        lines={[
          "친구와 나눈 대화 같은 다른 알림은 읽는 즉시 버립니다.",
          "결제 알림도 이 폰 안에만 저장하고 서버로 보내지 않습니다.",
          "카톡으로 카드 알림을 받으신다면 카톡 알림의 메시지 미리보기가 켜져 있어야 합니다.",
          "허용한 뒤부터 오는 알림을 읽습니다. 첫 구독은 결제가 두 번 쌓이면 확인됩니다.",
        ]}
      />

      {bridge ? (
        <div className="space-y-2">
          <PrimaryButton onClick={granted ? onGranted : () => bridge.openAccessSettings()}>
            {granted ? "이미 허용했어요 · 계속" : "알림 접근 허용하기"}
          </PrimaryButton>
          <BackButton onBack={onBack} />
        </div>
      ) : (
        <div className="space-y-2">
          <p className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4 text-xs leading-relaxed text-zinc-400">
            결제 알림 읽기는 <span className="text-zinc-200">구독모아 앱</span>에서 동작합니다. 안드로이드는
            카톡·문자·카드사 앱 알림을, 아이폰은 카드 결제 문자를 읽습니다.
          </p>
          <button
            type="button"
            onClick={onPreview}
            className="w-full rounded-xl bg-zinc-800 px-4 py-3.5 font-bold text-zinc-100 transition hover:bg-zinc-700"
          >
            샘플로 미리보기
          </button>
          <BackButton onBack={onBack} />
        </div>
      )}
    </div>
  );
}

/**
 * 아이폰은 다른 앱 알림을 읽을 수 없다. 단축어 "메시지" 자동화가 카드 문자를 앱에 넘기도록
 * 사용자가 한 번 만들어 둔다(ios/README.md). 앱은 자동화가 만들어졌는지 알 수 없으므로
 * "설정을 마쳤어요"로 넘어간다.
 */
function IosConnect({
  bridge,
  onBack,
  onDone,
}: {
  bridge: NativeBridge;
  onBack: () => void;
  onDone: () => void;
}) {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-zinc-100">카드 결제 문자를 받게 해 주세요</h1>
        <p className="mt-1.5 text-sm text-zinc-400">
          단축어 자동화를 한 번 만들어 두면, 결제 문자가 올 때마다 저절로 구독을 찾습니다.
        </p>
      </div>

      <Steps
        items={[
          ["단축어 앱 열기", "아래 버튼을 누르고 자동화 → ＋ → 메시지를 고릅니다"],
          ["\"원\"이 들어간 문자", "메시지에 포함에 원을 넣고 즉시 실행을 고릅니다"],
          ["구독모아 › 결제 알림 저장", "동작으로 추가하고 문자 내용에 단축어 입력을 넣으면 끝입니다"],
        ]}
      />

      <PrivacyNote
        lines={[
          "카드 알림을 문자로 받으셔야 합니다. 아이폰은 카톡·카드사 앱 알림을 다른 앱이 읽을 수 없게 막아 둡니다.",
          "카드 결제 문자만 저장하고, 다른 문자는 넘어오는 즉시 버립니다.",
          "결제 문자도 이 폰 안에만 저장하고 서버로 보내지 않습니다.",
          "설정한 뒤부터 오는 문자를 읽습니다. 첫 구독은 결제가 두 번 쌓이면 확인됩니다.",
        ]}
      />

      <div className="space-y-2">
        <PrimaryButton onClick={() => bridge.openAccessSettings()}>단축어 앱 열기</PrimaryButton>
        <button
          type="button"
          onClick={onDone}
          className="w-full rounded-xl bg-zinc-800 px-4 py-3.5 font-bold text-zinc-100 transition hover:bg-zinc-700"
        >
          설정을 마쳤어요
        </button>
        <BackButton onBack={onBack} />
      </div>
    </div>
  );
}

function Steps({ items }: { items: [string, string][] }) {
  return (
    <ol className="space-y-3">
      {items.map(([title, desc], i) => (
        <li key={title} className="flex gap-3 rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-zinc-800 text-xs font-bold text-zinc-300">
            {i + 1}
          </span>
          <div>
            <p className="font-medium text-zinc-100">{title}</p>
            <p className="mt-0.5 text-xs text-zinc-500">{desc}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}

function PrivacyNote({ lines }: { lines: string[] }) {
  return (
    <div className="space-y-2 rounded-xl border border-emerald-500/25 bg-emerald-500/5 p-4">
      <p className="text-sm font-semibold text-emerald-300">카드 결제 알림만 남깁니다</p>
      <ul className="space-y-1 text-xs leading-relaxed text-zinc-400">
        {lines.map((line) => (
          <li key={line}>· {line}</li>
        ))}
      </ul>
    </div>
  );
}

function PrimaryButton({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full rounded-xl bg-sky-500 px-4 py-3.5 font-bold text-sky-950 transition hover:bg-sky-400"
    >
      {children}
    </button>
  );
}

function BackButton({ onBack }: { onBack: () => void }) {
  return (
    <button
      type="button"
      onClick={onBack}
      className="w-full py-2 text-sm text-zinc-500 transition hover:text-zinc-300"
    >
      이전
    </button>
  );
}

function ResultStep({
  declared,
  mode,
  bridge,
}: {
  declared: ReadonlySet<string>;
  mode: Mode;
  bridge: NativeBridge | null;
}) {
  const live = mode === "live" && bridge !== null;
  // 앱에서 알림 읽기까지 마쳤다 — 다음부터 앱은 온보딩 대신 홈으로 연다
  useEffect(() => {
    if (live) writeJSON(STORAGE_KEYS.onboarded, true);
  }, [live]);
  const collected = live ? collectTransactions(readCapturedAlerts(bridge)) : null;
  const all = collected
    ? detectSubscriptions(collected.transactions, { today: kstDate(Date.now()) })
    : detectSubscriptions(SAMPLE_TRANSACTIONS, { today: SAMPLE_TODAY });
  const subs = all.filter((s) => s.active);
  const ended = all.filter((s) => !s.active);
  const monthly = totalMonthly(subs);
  const surprises = subs.filter((s) => !s.service || !declared.has(s.service.id));

  if (collected && subs.length === 0) {
    return <WatchingStep declared={declared} paymentCount={collected.transactions.length} ended={ended.length} />;
  }

  return (
    <div className="space-y-6">
      {!live && (
        <p className="text-center text-xs text-zinc-500">샘플 결제 내역으로 보여드리는 결과입니다</p>
      )}

      <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-6 text-center">
        <p className="text-xs font-medium text-zinc-500">찾은 구독</p>
        <p className="mt-1 text-3xl font-bold tracking-tight text-zinc-50">{subs.length}개</p>
        <p className="mt-1 text-sm text-zinc-400">
          매월 <span className="font-semibold text-zinc-200">{won(monthly)}</span>
          <span className="mx-1.5 text-zinc-600">·</span>연 {won(monthly * 12)}
        </p>
      </div>

      {surprises.length > 0 && (
        <section className="rounded-2xl border border-amber-500/30 bg-amber-500/5 p-5">
          <h2 className="text-sm font-bold text-amber-300">
            고르지 않으신 것 {surprises.length}개도 찾았어요
          </h2>
          <p className="mt-1 text-xs text-amber-200/70">잊고 계신 구독일 수 있습니다.</p>
          <ul className="mt-3 space-y-2">
            {surprises.map((s) => (
              <li key={s.merchantNormalized} className="flex items-center justify-between text-sm">
                <span className="flex items-center gap-2 text-zinc-200">
                  <span aria-hidden>{s.service ? iconFor(s.service.id) : "❓"}</span>
                  {s.displayName}
                </span>
                <span className="font-semibold text-zinc-100">
                  {won(monthlyEquivalent(s))}
                  <span className="text-xs font-normal text-zinc-500">/월</span>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {ended.length > 0 && (
        <p className="text-center text-xs text-zinc-500">
          예전에 쓰다 해지한 것으로 보이는 구독 {ended.length}개는 합계에서 뺐습니다
        </p>
      )}

      <StartLink />
    </div>
  );
}

/**
 * 알림 읽기를 막 허용한 직후. 과거 내역이 없으니 구독이 아직 확인되지 않았다.
 * 고른 구독을 "다음 결제 때 확인"으로 보여 주고, 지금까지 모은 결제 알림 수로 동작 중임을 알린다.
 */
/**
 * 알림 읽기를 막 허용한 직후. 과거 내역이 없으니 구독이 아직 확인되지 않았다.
 * 고른 구독을 "다음 결제 때 확인"으로 보여 주고, 지금까지 모은 결제 알림 수로 동작 중임을 알린다.
 */
function WatchingStep({
  declared,
  paymentCount,
  ended,
}: {
  declared: ReadonlySet<string>;
  paymentCount: number;
  ended: number;
}) {
  return (
    <div className="space-y-6">
      <WatchingCard paymentCount={paymentCount} />
      <DeclaredWaiting declared={declared} />
      {ended > 0 && (
        <p className="text-center text-xs text-zinc-500">해지한 것으로 보이는 구독 {ended}개는 뺐습니다</p>
      )}
      <StartLink />
    </div>
  );
}

function StartLink() {
  return (
    <Link
      href="/"
      className="block w-full rounded-xl bg-sky-500 px-4 py-3.5 text-center font-bold text-sky-950 transition hover:bg-sky-400"
    >
      시작하기
    </Link>
  );
}
