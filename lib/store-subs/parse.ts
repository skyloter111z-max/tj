/**
 * 앱스토어/구글플레이 구독 화면 스크린샷의 OCR 글자 → 구독 목록.
 *
 * 카드에 안 찍히는 인앱 구독(유튜브 프리미엄, 아이폰으로 결제한 넷플릭스 등)을 잡는 길이다.
 * 글자 인식(OCR)은 안드로이드 ML Kit가 폰에서 하고(네이티브), 여기서는 그 글자만 해석한다 —
 * 카드 알림을 네이티브가 받고 웹이 해석하는 것과 같은 구조다.
 *
 * 스토어 화면은 "서비스 이름" 줄과 "가격" 줄이 가까이 붙어 나온다. 사전에 있는 서비스만 뽑는다 —
 * 스토어 화면엔 광고·안내 문구도 많아, 아는 이름 + 가까운 가격이 함께 있을 때만 구독으로 본다.
 */

import type { DetectedSubscription } from "../detector";
import { matchMerchant, type ServiceDef } from "../merchants";

export type StoreSubscription = {
  service: ServiceDef;
  amount: number;
  cycle: "monthly" | "yearly";
};

/**
 * "₩14,900", "14,900원", "₩ 14,900"에서 금액을 뽑는다. 해외통화(US$ 등)는 건너뛴다.
 * 통화 표시(₩·원)나 천단위 쉼표가 있을 때만 가격으로 본다 — "Microsoft 365"의 365처럼
 * 이름에 든 숫자를 가격으로 오인하지 않기 위해서다.
 */
function priceOf(line: string): number | null {
  if (/US\$|USD|\$\s?\d|JPY|EUR|€|¥/.test(line)) return null;
  const num = "(\\d{1,3}(?:,\\d{3})+|\\d{3,})";
  const m =
    line.match(new RegExp("(?:₩|\\\\)\\s?" + num)) ?? // ₩14,900 / ₩17000
    line.match(new RegExp(num + "\\s*원")) ?? // 14,900원
    line.match(/(\d{1,3}(?:,\d{3})+)/); // 쉼표가 있는 숫자
  if (!m) return null;
  const n = Number(m[1]!.replace(/,/g, ""));
  return Number.isFinite(n) && n >= 100 ? n : null;
}

function cycleOf(line: string): "monthly" | "yearly" | null {
  if (/연간|\/\s?년|매년|년마다|annual|year/i.test(line)) return "yearly";
  if (/월간|\/\s?월|매월|월마다|month/i.test(line)) return "monthly";
  return null;
}

/**
 * OCR 글자를 줄 단위로 훑는다. 서비스 이름이 있는 줄을 찾으면, 그 줄부터 다음 2줄 안에서
 * 가격과 주기를 모은다. 같은 서비스가 여러 번 잡히면 한 번만 남긴다.
 */
export function parseStoreScreenshot(ocrText: string): StoreSubscription[] {
  const lines = ocrText
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
  const byId = new Map<string, StoreSubscription>();

  for (let i = 0; i < lines.length; i++) {
    const { service } = matchMerchant(lines[i]!);
    if (!service || byId.has(service.id)) continue;

    let amount: number | null = null;
    let cycle: "monthly" | "yearly" | null = null;
    // 이름 줄 자신과 다음 두 줄에서 가격·주기를 찾는다
    for (let j = i; j < Math.min(i + 3, lines.length); j++) {
      amount ??= priceOf(lines[j]!);
      cycle ??= cycleOf(lines[j]!);
    }
    if (amount === null) continue; // 가격을 못 찾으면 구독으로 치지 않는다
    byId.set(service.id, { service, amount, cycle: cycle ?? "monthly" });
  }

  return [...byId.values()];
}

const DAY_MS = 86_400_000;
const CYCLE_DAYS = { monthly: 30, yearly: 365 } as const;

function addDays(iso: string, days: number): string {
  return new Date(Date.parse(`${iso}T00:00:00Z`) + days * DAY_MS).toISOString().slice(0, 10);
}

/**
 * 스토어 스크린샷 구독을 구독 목록에 넣을 수 있게 바꾼다.
 * 스크린샷엔 과거 내역이 없으므로 결제 횟수·총액은 1회분으로만 둔다. 다음 결제일은 추정이다.
 */
export function storeSubToDetected(s: StoreSubscription, today: string): DetectedSubscription {
  return {
    service: s.service,
    displayName: s.service.name,
    merchantNormalized: s.service.name,
    amount: s.amount,
    cycle: s.cycle,
    nextChargeDate: addDays(today, CYCLE_DAYS[s.cycle]),
    confidence: 1,
    occurrences: 1,
    lastChargeDate: today,
    firstChargeDate: today,
    totalPaid: s.amount,
    priceChange: null,
    isNew: false,
    active: true,
    source: "store",
  };
}

/**
 * 카드에서 찾은 구독과 스토어에서 찾은 구독을 합친다. 같은 서비스가 양쪽에 있으면
 * 카드 쪽을 쓴다 — 실제 결제 내역(횟수·총액·다음 결제일)이 있기 때문이다.
 */
export function mergeStoreSubs(
  cardSubs: readonly DetectedSubscription[],
  storeSubs: readonly StoreSubscription[],
  today: string,
): DetectedSubscription[] {
  const haveCard = new Set(cardSubs.map((s) => s.service?.id).filter(Boolean));
  const extra = storeSubs
    .filter((s) => !haveCard.has(s.service.id))
    .map((s) => storeSubToDetected(s, today));
  return [...cardSubs, ...extra];
}

/** 브리지에 저장할 수 있는 납작한 형태 (ServiceDef는 직렬화하지 않는다) */
export type StoredStoreSub = { id: string; amount: number; cycle: "monthly" | "yearly" };

export function toStored(subs: readonly StoreSubscription[]): StoredStoreSub[] {
  return subs.map((s) => ({ id: s.service.id, amount: s.amount, cycle: s.cycle }));
}
