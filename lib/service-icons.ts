/**
 * 서비스 아이콘 — UI 전용.
 *
 * 도메인 사전(lib/merchants.ts)은 식별 규칙만 담는다. 표시용 이모지를 거기에 섞으면
 * 판정 로직과 화면이 같은 파일에서 바뀌게 되므로 분리한다.
 */

import { SERVICES, type ServiceCategory, type ServiceDef } from "./merchants";

const ICONS: Record<string, string> = {
  netflix: "🎬",
  disneyplus: "🏰",
  tving: "📺",
  wavve: "🌊",
  coupangplay: "⚽",
  youtubepremium: "▶️",
  chatgpt: "🤖",
  claude: "🧠",
  gemini: "✨",
  perplexity: "🔍",
  cursor: "⌨️",
  midjourney: "🎨",
  spotify: "🎵",
  melon: "🍈",
  coupangwow: "📦",
  naverplus: "🟢",
  icloud: "☁️",
  ms365: "📄",
};

export function iconFor(serviceId: string): string {
  return ICONS[serviceId] ?? "💳";
}

export const CATEGORY_LABELS: Record<ServiceCategory, string> = {
  ott: "OTT",
  ai: "AI",
  music: "음악",
  commerce: "쇼핑·멤버십",
  cloud: "클라우드·오피스",
  etc: "기타",
};

/** 카테고리별로 묶은 서비스 목록. 빈 카테고리는 내보내지 않는다 */
export function servicesByCategory(): { category: ServiceCategory; services: ServiceDef[] }[] {
  const order: ServiceCategory[] = ["ott", "ai", "music", "commerce", "cloud", "etc"];
  return order
    .map((category) => ({
      category,
      services: SERVICES.filter((s) => s.category === category),
    }))
    .filter((g) => g.services.length > 0);
}
