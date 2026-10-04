"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ServicePicker } from "@/components/ServicePicker";
import { detectSubscriptions, monthlyEquivalent, totalMonthly } from "@/lib/detector";
import { iconFor } from "@/lib/service-icons";
import { SAMPLE_TRANSACTIONS } from "@/lib/sample-data";

const won = (n: number) => `${n.toLocaleString("ko-KR")}원`;
const TODAY = "2026-10-04";
const STORAGE_KEY = "submoa.declared";

type Step = "services" | "connect" | "scanning" | "result";

/** 스캔 단계 — spec/v5 §3.1의 1~3단계를 사용자에게 보여주는 문구 */
const SCAN_STAGES = [
  "카드 목록을 확인하고 있어요",
  "13개월 청구 내역을 훑고 있어요",
  "정기결제를 찾고 있어요",
  "연 구독을 확인하고 있어요",
] as const;

export default function OnboardingPage() {
  const [step, setStep] = useState<Step>("services");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [stage, setStage] = useState(0);

  // 선택은 브라우저에만 남는다. 저장이 막힌 환경(시크릿 모드 등)에서도 동작해야 한다.
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) setSelected(new Set(JSON.parse(raw) as string[]));
    } catch {
      // 저장소를 못 읽어도 온보딩은 진행된다
    }
  }, []);

  function persist(next: Set<string>) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify([...next]));
    } catch {
      // 무시 — 선언은 힌트일 뿐이라 없어도 스캔은 된다
    }
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
          onBack={() => setStep("services")}
          onConnect={() => {
            setStage(0);
            setStep("scanning");
          }}
        />
      )}

      {step === "scanning" && (
        <ScanningStep stage={stage} setStage={setStage} onDone={() => setStep("result")} />
      )}

      {step === "result" && <ResultStep declared={selected} />}
    </div>
  );
}

function StepDots({ step }: { step: Step }) {
  const order: Step[] = ["services", "connect", "scanning", "result"];
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

function ConnectStep({ onBack, onConnect }: { onBack: () => void; onConnect: () => void }) {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-zinc-100">카드를 연결해 주세요</h1>
        <p className="mt-1.5 text-sm text-zinc-400">한 번만 하면 나머지는 자동입니다.</p>
      </div>

      <ol className="space-y-3">
        {[
          ["1", "휴대폰 본인인증", "오픈뱅킹 인증 화면으로 넘어갑니다"],
          ["2", "ARS 동의", "전화를 받아 동의하면 끝입니다"],
          ["3", "완료", "카드사 앱은 필요하지 않습니다"],
        ].map(([n, title, desc]) => (
          <li key={n} className="flex gap-3 rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-zinc-800 text-xs font-bold text-zinc-300">
              {n}
            </span>
            <div>
              <p className="font-medium text-zinc-100">{title}</p>
              <p className="mt-0.5 text-xs text-zinc-500">{desc}</p>
            </div>
          </li>
        ))}
      </ol>

      <div className="space-y-2 rounded-xl border border-emerald-500/25 bg-emerald-500/5 p-4">
        <p className="text-sm font-semibold text-emerald-300">읽기 전용입니다</p>
        <ul className="space-y-1 text-xs leading-relaxed text-zinc-400">
          <li>· 결제 내역을 보기만 합니다. 출금·이체 권한은 요청하지 않습니다.</li>
          <li>· 금융결제원 오픈뱅킹을 통해 조회하며, 비밀번호를 저장하지 않습니다.</li>
          <li>· 가족카드 이용내역은 신용정보법에 따라 제공되지 않습니다.</li>
        </ul>
      </div>

      <div className="space-y-2">
        <button
          type="button"
          onClick={onConnect}
          className="w-full rounded-xl bg-sky-500 px-4 py-3.5 font-bold text-sky-950 transition hover:bg-sky-400"
        >
          카드 연결하기
        </button>
        <button
          type="button"
          onClick={onBack}
          className="w-full py-2 text-sm text-zinc-500 transition hover:text-zinc-300"
        >
          이전
        </button>
      </div>
    </div>
  );
}

function ScanningStep({
  stage,
  setStage,
  onDone,
}: {
  stage: number;
  setStage: (n: number) => void;
  onDone: () => void;
}) {
  // 실제 연동 전까지는 단계 진행을 흉내 낸다. 연동 후에는 runSignupScan의
  // 진행 콜백으로 교체한다.
  //
  // 콜백을 의존성에 넣으면 안 된다. setStage가 부모를 리렌더하면 부모가 인라인
  // 화살표 함수를 새로 만들고, 의존성이 바뀌어 인터벌이 초기화되면서 진행이
  // 1단계에서 영원히 되감긴다. 최신 콜백은 ref로 들고, 효과는 마운트 때 한 번만 돈다.
  const cb = useRef({ setStage, onDone });
  cb.current = { setStage, onDone };

  useEffect(() => {
    let i = 0;
    const timer = setInterval(() => {
      i += 1;
      if (i < SCAN_STAGES.length) {
        cb.current.setStage(i);
      } else {
        clearInterval(timer);
        cb.current.onDone();
      }
    }, 850);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="space-y-6 py-8">
      <h1 className="text-center text-xl font-bold text-zinc-100">구독을 찾고 있어요</h1>
      <ul className="space-y-3">
        {SCAN_STAGES.map((label, i) => {
          const done = i < stage;
          const active = i === stage;
          return (
            <li key={label} className="flex items-center gap-3">
              <span
                className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs ${
                  done
                    ? "bg-emerald-400/20 text-emerald-300"
                    : active
                      ? "bg-sky-400/20 text-sky-300"
                      : "bg-zinc-800 text-zinc-600"
                }`}
              >
                {done ? "✓" : active ? "…" : ""}
              </span>
              <span
                className={`text-sm ${
                  done ? "text-zinc-400" : active ? "font-medium text-zinc-100" : "text-zinc-600"
                }`}
              >
                {label}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function ResultStep({ declared }: { declared: ReadonlySet<string> }) {
  // 실제 연동 전까지 샘플 거래로 엔진을 돌린다. 결과는 진짜 판정 결과다.
  const subs = detectSubscriptions(SAMPLE_TRANSACTIONS, { today: TODAY });
  const monthly = totalMonthly(subs);
  const surprises = subs.filter((s) => !s.service || !declared.has(s.service.id));

  return (
    <div className="space-y-6">
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

      <Link
        href="/"
        className="block w-full rounded-xl bg-sky-500 px-4 py-3.5 text-center font-bold text-sky-950 transition hover:bg-sky-400"
      >
        시작하기
      </Link>
    </div>
  );
}
