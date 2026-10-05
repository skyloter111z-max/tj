/**
 * "구독 화면으로 확인하기"가 열어서 읽을 대상 목록.
 *
 * 사용자가 고른 서비스(OTT·AI 등)의 구독·계정 페이지와, 스토어 전체 화면을 한 번의 화면 캡처 동의로
 * 차례로 열어 읽는다(ScreenCaptureService 큐). 사전(lib/merchants.ts)에서 "금액이 보이는 페이지"가
 * 있는 서비스만 대상으로 삼는다.
 */

import { SERVICES, type ServiceCategory, type ServiceDef } from "./merchants";
import { iconFor } from "./service-icons";

export type CaptureTarget = { key: string; id: string; name: string; icon: string; url: string };
export type CaptureGroup = { label: string; targets: CaptureTarget[] };

const PLAY_URL = "https://play.google.com/store/account/subscriptions";
const APPLE_URL = "https://apps.apple.com/account/subscriptions";

/** 그 서비스의 구독 금액이 보이는 페이지. 없으면 대상에서 뺀다 */
export function captureUrlOf(s: ServiceDef): string | undefined {
  return s.manageUrl ?? s.cancelUrl;
}

function fromCategory(category: ServiceCategory): CaptureTarget[] {
  return SERVICES.filter((s) => s.category === category && captureUrlOf(s)).map((s) => ({
    key: s.id,
    id: s.id,
    name: s.name,
    icon: iconFor(s.id),
    url: captureUrlOf(s)!,
  }));
}

/** 고를 수 있는 대상, 묶음별. 스토어 전체가 가장 확실해 맨 앞에 둔다 */
export function captureGroups(): CaptureGroup[] {
  return [
    {
      label: "스토어 한 번에",
      targets: [
        { key: "store-play", id: "", name: "구글플레이 전체", icon: "▶️", url: PLAY_URL },
        { key: "store-apple", id: "", name: "앱스토어(애플) 전체", icon: "🍎", url: APPLE_URL },
      ],
    },
    { label: "영상 (OTT)", targets: fromCategory("ott") },
    { label: "AI", targets: fromCategory("ai") },
  ].filter((g) => g.targets.length > 0);
}

/**
 * 기본 선택: 구글플레이 전체 + OTT + AI. 앱스토어(애플)는 안드로이드에서 애플 로그인이 거의 안 돼
 * 있어 빈 화면만 잡히므로 기본 해제한다(사용자가 직접 켤 수 있다).
 */
export function defaultSelection(): Set<string> {
  const keys = new Set<string>();
  for (const g of captureGroups()) for (const t of g.targets) keys.add(t.key);
  keys.delete("store-apple");
  return keys;
}

export type QueueItem = { id: string; url: string; name: string };

/**
 * 고른 대상으로 캡처 큐를 만든다. 같은 주소(예: 유튜브 프리미엄과 구글플레이 전체)는 한 번만 연다.
 * name은 읽는 동안 떠 있는 안내창에 보인다.
 */
export function buildQueue(selectedKeys: ReadonlySet<string>): QueueItem[] {
  const out: QueueItem[] = [];
  const seenUrl = new Set<string>();
  for (const g of captureGroups()) {
    for (const t of g.targets) {
      if (!selectedKeys.has(t.key) || seenUrl.has(t.url)) continue;
      seenUrl.add(t.url);
      out.push({ id: t.id, url: t.url, name: t.name });
    }
  }
  return out;
}
