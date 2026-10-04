/**
 * 브라우저 저장소. 시크릿 모드처럼 막힌 환경에서도 화면은 떠야 하므로 실패는 삼킨다.
 * 앱(WebView)에서는 기기 안에만 남는다.
 */
export const STORAGE_KEYS = {
  /** 온보딩에서 고른 구독 id 목록 */
  declared: "submoa.declared",
  /** 앱에서 알림 읽기 설정까지 마쳤는가 */
  onboarded: "submoa.onboarded",
  /** 구독 키 → 처음 찾은 날짜 (lib/home.ts) */
  seen: "submoa.seen",
} as const;

export function readJSON<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

export function writeJSON(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // 저장이 막혀도 화면은 동작한다
  }
}
