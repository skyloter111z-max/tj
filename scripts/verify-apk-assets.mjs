#!/usr/bin/env node
/**
 * APK 안의 웹 앱이 온전한지 확인한다: assets/web/의 모든 HTML이 참조하는 /_next/ 파일이
 * 실제로 APK에 들어 있는가.
 *
 * aapt는 기본값으로 `_`로 시작하는 폴더를 빼 버린다. 그러면 HTML만 들어가 화면이 깨지는데,
 * 빌드는 성공하고 out/을 직접 띄운 브라우저 테스트도 통과한다 — APK를 열어 봐야만 잡힌다.
 *
 *   node scripts/verify-apk-assets.mjs android/app/build/outputs/apk/debug/app-debug.apk
 */
import { execFileSync } from "node:child_process";

const apk = process.argv[2];
if (!apk) {
  console.error("사용법: node scripts/verify-apk-assets.mjs <apk 경로>");
  process.exit(2);
}

const entries = new Set(execFileSync("unzip", ["-Z1", apk], { encoding: "utf8" }).split("\n").filter(Boolean));
const pages = [...entries].filter((e) => e.startsWith("assets/web/") && e.endsWith(".html"));
if (pages.length === 0) {
  console.error("assets/web/에 HTML이 없습니다. 저장소 루트에서 npm run export를 먼저 실행하세요.");
  process.exit(1);
}

const missing = new Map();
let referenced = 0;
for (const page of pages) {
  const html = execFileSync("unzip", ["-p", apk, page], { encoding: "utf8" });
  const refs = new Set(html.match(/\/_next\/[^"'\s)\\]+/g) ?? []);
  for (const ref of refs) {
    referenced++;
    // "[id]" 같은 경로는 HTML에 %5Bid%5D로 들어 있다. WebView도 디코딩한 경로로 찾는다.
    const entry = `assets/web${decodeURIComponent(ref.split("?")[0])}`;
    if (!entries.has(entry)) missing.set(entry, page);
  }
}

if (missing.size > 0) {
  console.error(`APK에 없는 파일 ${missing.size}개 (HTML ${pages.length}개가 참조):`);
  for (const [entry, page] of [...missing].slice(0, 10)) console.error(`  ${entry}  ← ${page}`);
  process.exit(1);
}
console.log(`OK: HTML ${pages.length}개, 참조 ${referenced}건 모두 APK에 있음`);
