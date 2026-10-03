import type { Party } from "@/lib/parties";
import { emptySlotCount, isFull } from "@/lib/parties";

/**
 * 파티 슬롯. 게임의 파티 모집창을 의도한 UI다.
 *
 * 정원 수만큼의 열을 가진 그리드로 고정한다. flex-wrap을 쓰면 모바일 폭에서
 * 마지막 슬롯이 다음 줄로 밀려 "4인 한 줄" 그림이 깨진다.
 */
export function PartySlots({ party, size = "md" }: { party: Party; size?: "sm" | "md" }) {
  const empty = emptySlotCount(party);
  const full = isFull(party);

  const box =
    size === "sm"
      ? "aspect-square rounded-xl text-lg"
      : "aspect-square rounded-2xl text-2xl sm:text-3xl";
  const label = size === "sm" ? "text-[10px]" : "text-[11px] sm:text-xs";
  const gap = size === "sm" ? "gap-2" : "gap-2.5 sm:gap-3";

  return (
    <div>
      <div
        className={`grid ${gap}`}
        style={{ gridTemplateColumns: `repeat(${party.capacity}, minmax(0, 1fr))` }}
      >
        {party.members.map((m, i) => (
          <div key={m.id} className="flex min-w-0 flex-col items-center gap-1.5">
            <div
              className={`${box} animate-slot-in flex w-full items-center justify-center border-2 border-emerald-400/70 bg-emerald-400/10 shadow-[0_0_20px_-4px_rgba(52,211,153,0.5)]`}
              style={{ animationDelay: `${i * 70}ms` }}
              aria-label={`${i + 1}번 자리: ${m.nickname}`}
            >
              <span aria-hidden>{m.emoji}</span>
            </div>
            <span className={`${label} w-full truncate text-center font-medium text-zinc-300`}>
              {m.nickname}
            </span>
          </div>
        ))}

        {Array.from({ length: empty }).map((_, i) => (
          <div key={`empty-${i}`} className="flex min-w-0 flex-col items-center gap-1.5">
            <div
              className={`${box} relative flex w-full items-center justify-center border-2 border-dashed border-zinc-600 bg-zinc-800/40`}
              aria-label={`${party.members.length + i + 1}번 자리: 모집 중`}
            >
              {i === 0 && (
                <span
                  aria-hidden
                  className="absolute -inset-px animate-pulse-ring rounded-2xl border-2 border-sky-400/60"
                />
              )}
              <span aria-hidden className="text-zinc-500">
                +
              </span>
            </div>
            <span className={`${label} w-full truncate text-center text-zinc-500`}>모집 중</span>
          </div>
        ))}
      </div>

      {full && (
        <p className="pt-3 text-center text-xs font-semibold text-emerald-400">
          정원이 모두 찼습니다
        </p>
      )}
    </div>
  );
}

/** "3 / 4" 진행 표시 + 막대 */
export function PartyProgress({ party }: { party: Party }) {
  const filled = party.members.length;
  const pct = Math.round((filled / party.capacity) * 100);
  const full = isFull(party);

  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between text-xs">
        <span className="font-medium text-zinc-400">모인 인원</span>
        <span className={full ? "font-bold text-emerald-400" : "font-bold text-sky-400"}>
          {filled} / {party.capacity}
        </span>
      </div>
      <div
        className="h-1.5 overflow-hidden rounded-full bg-zinc-800"
        role="progressbar"
        aria-valuenow={filled}
        aria-valuemin={0}
        aria-valuemax={party.capacity}
      >
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            full ? "bg-emerald-400" : "bg-sky-400"
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
