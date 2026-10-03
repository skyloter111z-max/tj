import Link from "next/link";
import { notFound } from "next/navigation";
import { PartyProgress, PartySlots } from "@/components/PartySlots";
import { DEMO_PARTIES, findParty, isFull, savingsPerMonth, savingsPercent } from "@/lib/parties";
import { buildReferralUrl, DISCLOSURE, hasPromoCode } from "@/lib/referral";

const won = (n: number) => `${n.toLocaleString("ko-KR")}원`;

export function generateStaticParams() {
  return DEMO_PARTIES.map((p) => ({ id: p.id }));
}

export default async function PartyDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const party = findParty(id);
  if (!party) notFound();

  const full = isFull(party);
  const referral = buildReferralUrl({ slug: party.gamsgoSlug, partyId: party.id });

  return (
    <div className="space-y-6">
      <Link href="/party" className="inline-block text-sm text-zinc-500 hover:text-zinc-300">
        ← 파티 목록
      </Link>

      <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-6">
        <div className="mb-6 text-center">
          <h1 className="text-lg font-bold text-zinc-100">
            {party.serviceName} 파티원 찾습니다
          </h1>
          <p className="mt-2 text-sm text-zinc-400">
            1인 <span className="text-base font-bold text-zinc-100">{won(party.sharedPrice)}</span>
            <span className="mx-2 text-zinc-600">·</span>
            매월 <span className="font-semibold text-emerald-400">{won(savingsPerMonth(party))}</span>{" "}
            절약 ({savingsPercent(party)}%)
          </p>
        </div>

        <div className="mb-6">
          <PartySlots party={party} />
        </div>

        <div className="mb-6">
          <PartyProgress party={party} />
        </div>

        {full ? (
          <a
            href={referral}
            target="_blank"
            rel="noopener noreferrer nofollow sponsored"
            className="block w-full rounded-xl bg-emerald-500 px-4 py-3.5 text-center font-bold text-emerald-950 transition hover:bg-emerald-400"
          >
            겜스고에서 자리 받기
          </a>
        ) : (
          <button
            type="button"
            className="w-full rounded-xl bg-sky-500 px-4 py-3.5 text-center font-bold text-sky-950 transition hover:bg-sky-400"
          >
            이 파티 참여하기
          </button>
        )}

        {!hasPromoCode() && (
          <p className="mt-3 text-center text-xs text-amber-400/80">
            NEXT_PUBLIC_GAMSGO_PROMO 미설정 — 커미션이 집계되지 않습니다
          </p>
        )}
      </div>

      <div className="space-y-3 rounded-2xl border border-zinc-800 bg-zinc-900/40 p-5 text-sm">
        <h2 className="font-semibold text-zinc-200">가입 전 확인</h2>
        <ul className="space-y-2 text-xs leading-relaxed text-zinc-400">
          <li>
            · 계정은 겜스고가 제공하고 관리합니다. 구독모아는 결제·계정·분쟁의 당사자가 아닙니다.
          </li>
          <li>
            · 서비스 약관상 계정 공유가 제한될 수 있고, 그 경우 계정이 정지될 수 있습니다.
          </li>
          <li>
            · AI 구독은 같은 계정을 쓰면 대화 내용이 다른 파티원에게 보일 수 있습니다. 업무 문서나
            개인적인 내용을 입력하지 마십시오.
          </li>
        </ul>
        <p className="border-t border-zinc-800 pt-3 text-xs text-zinc-500">{DISCLOSURE}</p>
      </div>
    </div>
  );
}
