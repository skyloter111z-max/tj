import { findService } from "./merchants";

/**
 * 다른 멤버십을 통해 청구되는 구독의 표시 문구. 해당 없으면 null.
 *   금액 0  → "네이버플러스에 포함"   (멤버십 요금에 들어 있어 따로 안 나간다)
 *   금액 >0 → "네이버플러스로 청구"   (업그레이드 차액 등이 그 멤버십으로 함께 나간다)
 */
export function viaLabel(s: { amount: number; billedVia?: string }): string | null {
  if (!s.billedVia) return null;
  const name = findService(s.billedVia)?.name ?? s.billedVia;
  return s.amount === 0 ? `${name}에 포함` : `${name}로 청구`;
}
