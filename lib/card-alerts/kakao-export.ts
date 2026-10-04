/**
 * 카카오톡 "대화 내용 내보내기" 텍스트 → AlertMessage[].
 *
 * 형식은 기기마다 다르다. 모바일은 메시지마다 날짜·시각이 줄 앞에 붙고,
 * PC는 날짜 구분선 아래에 [이름] [시각]이 붙는다:
 *
 *   모바일   2026년 10월 3일 오후 9:24, 삼성카드 : 삼성1088승인 김*진
 *   (구형)   2026. 10. 3. 오후 9:24, 삼성카드 : 삼성1088승인 김*진
 *   PC       --------------- 2026년 10월 3일 토요일 ---------------
 *            [삼성카드] [오후 9:24] 삼성1088승인 김*진
 *
 * 여러 줄 메시지는 다음 줄에 이어진다. 머리말("저장한 날짜 : ...")과
 * 모바일 날짜 구분선은 버린다. 구분선은 메시지 줄에서 ", 이름 : 내용"이 빠진 모양이다
 * ("2026년 10월 3일 오후 9:24").
 *
 * 모바일 형식은 실제 내보내기 파일(UTF-8 BOM, CRLF·LF 혼용)로 확인했다.
 * 구형·PC 형식은 아직 실제 파일로 확인하지 않았다.
 */

import type { AlertMessage } from "./parse";

const MOBILE_MSG = /^(\d{4})년 (\d{1,2})월 (\d{1,2})일 (?:오전|오후) \d{1,2}:\d{2}, .+? : (.*)$/;
const LEGACY_MSG = /^(\d{4})\. (\d{1,2})\. (\d{1,2})\. (?:오전|오후) \d{1,2}:\d{2}, .+? : (.*)$/;
const PC_DATE = /^-+ (\d{4})년 (\d{1,2})월 (\d{1,2})일 \S+요일 -+$/;
const PC_MSG = /^\[.+?\] \[(?:오전|오후) \d{1,2}:\d{2}\] (.*)$/;
const DATE_DIVIDER = /^\d{4}년 \d{1,2}월 \d{1,2}일 (?:\S+요일|(?:오전|오후) \d{1,2}:\d{2})$/;

function isoDate(y: string, m: string, d: string): string {
  return `${y}-${m.padStart(2, "0")}-${d.padStart(2, "0")}`;
}

export function parseKakaoExport(text: string): AlertMessage[] {
  const messages: AlertMessage[] = [];
  let current: AlertMessage | null = null;
  let pcDate: string | null = null;

  const start = (receivedAt: string, firstLine: string) => {
    current = { receivedAt, body: firstLine };
    messages.push(current);
  };

  for (const line of text.replace(/^\uFEFF/, "").split(/\r?\n/)) {
    let m: RegExpMatchArray | null;

    if ((m = line.match(MOBILE_MSG)) || (m = line.match(LEGACY_MSG))) {
      start(isoDate(m[1]!, m[2]!, m[3]!), m[4]!);
    } else if ((m = line.match(PC_DATE))) {
      pcDate = isoDate(m[1]!, m[2]!, m[3]!);
      current = null;
    } else if (pcDate && (m = line.match(PC_MSG))) {
      start(pcDate, m[1]!);
    } else if (DATE_DIVIDER.test(line)) {
      current = null;
    } else if (current) {
      (current as AlertMessage).body += `\n${line}`;
    }
  }

  for (const msg of messages) msg.body = msg.body.trimEnd();
  return messages;
}

/** 내보내기 파일이 덮는 기간. 사용자에게 "몇 달치를 읽었는지" 보여줄 때 쓴다 */
export function exportSpan(messages: readonly AlertMessage[]): { from: string; to: string } | null {
  if (messages.length === 0) return null;
  let from = messages[0]!.receivedAt;
  let to = from;
  for (const { receivedAt } of messages) {
    if (receivedAt < from) from = receivedAt;
    if (receivedAt > to) to = receivedAt;
  }
  return { from, to };
}
