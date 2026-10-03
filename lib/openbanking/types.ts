/**
 * 오픈뱅킹 카드 API 응답 타입.
 *
 * 명세: developers.kftc.or.kr/dev/openapi/open-banking/{bills, bills_detail}
 * 2026-10-03 확인. 금액·날짜가 모두 **문자열**로 오고, 금액은 음수가 될 수 있다.
 *
 * ⚠️ 카드목록조회는 공개 명세를 확인하지 못했다. 아래 CardListResponse는
 *    추정이며 이용계약 후 실제 응답으로 교정해야 한다 (spec/v5 §1.5 C7).
 */

/** 모든 응답에 공통으로 붙는 헤더 */
export type ApiHeader = {
  api_tran_id: string;
  api_tran_dtm: string;
  /** "A0000"이 정상 */
  rsp_code: string;
  rsp_message: string;
  bank_tran_id?: string;
  bank_tran_date?: string;
  bank_code_tran?: string;
  /** 참가기관(카드사) 응답코드. "000"이 정상 */
  bank_rsp_code?: string;
  bank_rsp_message?: string;
};

/** 페이지네이션. next_page_yn이 "Y"면 befor_inquiry_trace_info로 이어 조회한다 */
export type Pagination = {
  next_page_yn: "Y" | "N";
  befor_inquiry_trace_info: string;
};

export type Card = {
  /** 카드사 대표코드 (금융기관 공동코드) */
  bank_code_std: string;
  /** 회원 금융회사 코드 */
  member_bank_code: string;
  /** 카드 식별값 */
  card_id: string;
  card_name?: string;
};

export type CardListResponse = ApiHeader & {
  user_seq_no: string;
  card_cnt?: string;
  card_list: Card[];
};

/** 카드청구기본정보조회 — 월별 청구 총액. 가맹점명 없음 */
export type BillBasicItem = {
  /** 청구년월 YYYYMM */
  charge_month: string;
  /** 청구금액 (원) */
  charge_amt: string;
  /** 결제일 (일) */
  settlement_day?: string;
  /** 실제 결제일 YYYYMMDD */
  settlement_date?: string;
  card_id?: string;
  /**
   * 결제순번. 카드청구상세정보조회의 필수 파라미터다.
   * 명세 주석: "카드청구기본정보조회 응답 메시지 상의 청구년월 및 결제순번"
   */
  settlement_seq_no?: string;
};

export type BillBasicResponse = ApiHeader &
  Pagination & {
    user_seq_no: string;
    bill_cnt?: string;
    bill_list: BillBasicItem[];
  };

/** 카드청구상세정보조회 — 건별 거래. 가맹점명이 마스킹돼 온다 */
export type BillDetailItem = {
  card_value: string;
  /** 사용일자 YYYYMMDD */
  paid_date: string;
  /** 사용시간 hhmmss */
  paid_time?: string;
  /** 이용금액 (원). 음수 가능 — 취소·환불 */
  paid_amt: string;
  /** 🔴 마스킹된 가맹점명. 예시 "오픈**" */
  merchant_name_masked: string;
  /** 신용판매 수수료 */
  credit_fee_amt?: string;
  /** 상품 구분 */
  product_type?: string;
};

export type BillDetailResponse = ApiHeader &
  Pagination & {
    user_seq_no: string;
    /** 현재 페이지 조회 건수. 한 페이지 최대 20건 */
    bill_detail_cnt: string;
    bill_list: BillDetailItem[];
  };

export const RSP_OK = "A0000";

export function isOk(res: ApiHeader): boolean {
  return res.rsp_code === RSP_OK;
}
