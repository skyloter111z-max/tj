/**
 * 파티 모집 — 관심 등록 모델.
 *
 * 겜스고는 자동 매칭이므로 사용자가 파티원을 직접 모을 필요가 없다.
 * 따라서 슬롯은 "같은 계정에 함께 들어갈 4명"이 아니라
 * "지금 이 서비스를 찾고 있는 사람 수"다. 실제 관심 카운터이며,
 * 채워진 슬롯이 가짜가 되지 않는다.
 *
 * 정원이 차면 모인 사람들에게 함께 겜스고 링크를 보낸다.
 */

export type SlotMember = {
  id: string;
  nickname: string;
  /** 아바타 대신 쓰는 이모지 한 글자 */
  emoji: string;
  joinedAt: string;
};

export type Party = {
  id: string;
  serviceId: string;
  serviceName: string;
  /** 겜스고 상품 슬러그 */
  gamsgoSlug: string;
  /** 공식 정가 (월) */
  officialPrice: number;
  /** 겜스고 기준 1인 월 가격 */
  sharedPrice: number;
  capacity: number;
  members: SlotMember[];
  createdAt: string;
};

export function filledCount(party: Party): number {
  return party.members.length;
}

export function isFull(party: Party): boolean {
  return party.members.length >= party.capacity;
}

export function emptySlotCount(party: Party): number {
  return Math.max(0, party.capacity - party.members.length);
}

/** 1인당 절약액 (월) */
export function savingsPerMonth(party: Party): number {
  return Math.max(0, party.officialPrice - party.sharedPrice);
}

export function savingsPercent(party: Party): number {
  if (party.officialPrice === 0) return 0;
  return Math.round((savingsPerMonth(party) / party.officialPrice) * 100);
}

/**
 * 데모용 파티 목록.
 * 가격은 2026년 실측 기준 (spec/v4 §0, §1.3):
 *   ChatGPT Plus 29,000 / Claude Pro 27,000 / Perplexity Pro 27,000
 *   넷플릭스 프리미엄 17,000 / 디즈니+ / 티빙
 *   겜스고 ChatGPT ≈ 8,100원 (6인)
 */
export const DEMO_PARTIES: Party[] = [
  {
    id: "p-chatgpt-1",
    serviceId: "chatgpt",
    serviceName: "ChatGPT Plus",
    gamsgoSlug: "chatgpt",
    officialPrice: 29000,
    sharedPrice: 8100,
    capacity: 4,
    members: [
      { id: "m1", nickname: "새벽코딩", emoji: "🦊", joinedAt: "2026-10-01" },
      { id: "m2", nickname: "논문지옥", emoji: "🐧", joinedAt: "2026-10-02" },
      { id: "m3", nickname: "기획자K", emoji: "🐻", joinedAt: "2026-10-03" },
    ],
    createdAt: "2026-10-01",
  },
  {
    id: "p-netflix-1",
    serviceId: "netflix",
    serviceName: "넷플릭스 프리미엄",
    gamsgoSlug: "netflix",
    officialPrice: 17000,
    sharedPrice: 4800,
    capacity: 4,
    members: [
      { id: "m4", nickname: "주말몰아보기", emoji: "🐱", joinedAt: "2026-10-02" },
      { id: "m5", nickname: "드라마덕", emoji: "🐰", joinedAt: "2026-10-03" },
    ],
    createdAt: "2026-10-02",
  },
  {
    id: "p-claude-1",
    serviceId: "claude",
    serviceName: "Claude Pro",
    gamsgoSlug: "claude",
    officialPrice: 27000,
    sharedPrice: 7900,
    capacity: 4,
    members: [{ id: "m6", nickname: "글쓰는사람", emoji: "🦉", joinedAt: "2026-10-03" }],
    createdAt: "2026-10-03",
  },
  {
    id: "p-disney-1",
    serviceId: "disneyplus",
    serviceName: "디즈니+",
    gamsgoSlug: "disney",
    officialPrice: 13900,
    sharedPrice: 4200,
    capacity: 4,
    members: [
      { id: "m7", nickname: "마블올인", emoji: "🐯", joinedAt: "2026-09-30" },
      { id: "m8", nickname: "애니보는중", emoji: "🐨", joinedAt: "2026-10-01" },
      { id: "m9", nickname: "심슨팬", emoji: "🐸", joinedAt: "2026-10-02" },
      { id: "m10", nickname: "주말러", emoji: "🦝", joinedAt: "2026-10-03" },
    ],
    createdAt: "2026-09-30",
  },
];

export function findParty(id: string): Party | undefined {
  return DEMO_PARTIES.find((p) => p.id === id);
}
