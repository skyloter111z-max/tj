import { PartyCard } from "@/components/PartyCard";
import { DEMO_PARTIES } from "@/lib/parties";
import { DISCLOSURE } from "@/lib/referral";

export default function PartyListPage() {
  const open = DEMO_PARTIES.filter((p) => p.members.length < p.capacity);
  const full = DEMO_PARTIES.filter((p) => p.members.length >= p.capacity);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-zinc-100">파티 찾기</h1>
        <p className="mt-1 text-sm text-zinc-400">
          같은 구독을 찾는 사람이 모이면 함께 가입합니다.
        </p>
      </div>

      <section className="space-y-3">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
          모집 중 {open.length}
        </h2>
        {open.map((p) => (
          <PartyCard key={p.id} party={p} />
        ))}
      </section>

      {full.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
            정원 마감 {full.length}
          </h2>
          {full.map((p) => (
            <PartyCard key={p.id} party={p} />
          ))}
        </section>
      )}

      <p className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3 text-xs leading-relaxed text-zinc-500">
        {DISCLOSURE}
      </p>
    </div>
  );
}
