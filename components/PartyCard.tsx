import Link from "next/link";
import type { Party } from "@/lib/parties";
import { isFull, savingsPercent } from "@/lib/parties";
import { PartyProgress, PartySlots } from "./PartySlots";

const won = (n: number) => `${n.toLocaleString("ko-KR")}원`;

export function PartyCard({ party }: { party: Party }) {
  const full = isFull(party);

  return (
    <Link
      href={`/party/${party.id}`}
      className="group block rounded-2xl border border-zinc-800 bg-zinc-900/60 p-5 transition hover:border-zinc-700 hover:bg-zinc-900"
    >
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold text-zinc-100 group-hover:text-white">
            {party.serviceName} 파티원 찾습니다
          </h3>
          <p className="mt-0.5 text-sm text-zinc-400">
            1인 <span className="font-semibold text-zinc-200">{won(party.sharedPrice)}</span>
            <span className="mx-1.5 text-zinc-600">·</span>
            <span className="text-zinc-500 line-through">{won(party.officialPrice)}</span>
          </p>
        </div>
        <span
          className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-bold ${
            full
              ? "bg-emerald-400/15 text-emerald-300"
              : "bg-sky-400/15 text-sky-300"
          }`}
        >
          {savingsPercent(party)}% 절약
        </span>
      </div>

      <div className="mb-4">
        <PartySlots party={party} size="sm" />
      </div>

      <PartyProgress party={party} />
    </Link>
  );
}
