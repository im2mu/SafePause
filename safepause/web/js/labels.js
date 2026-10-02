/* 화면에 쓰는 쉬운 말 이름표. 당사자 화면에는 '주의·고위험' 대신 '확인해요·꼭 확인해요'를 쓴다
 * (전문 용어는 AI 성능 확인 표에만). 카드 문장 자체는 파이썬 explain/easy_card.py가 만든다.
 * v0.3: 신호 이름은 지시어(~보내기)가 아니라 일어난 일을 나타내는 명사형으로 쓴다. */
export const SIGNALS = ["night_repeat_transfer", "payee_surge", "micropay_surge", "new_merchant_high_value", "multi_line_telecom"];

export const SIGNAL_KO = {
  night_repeat_transfer: "밤 시간 잦은 이체",
  payee_surge: "한 사람에게 송금 집중",
  micropay_surge: "휴대폰 소액결제 급증",
  new_merchant_high_value: "처음 가는 곳 큰 금액 결제",
  multi_line_telecom: "휴대폰 요금 여러 회선",
};
// 이력이 짧아 처음인지 알 수 없을 때(newness_unknown) 쓰는 중립 이름표(카드 문구와 맞춤)
export const SIGNAL_KO_NEUTRAL = { new_merchant_high_value: "큰 금액 결제" };
// 신호 선 아이콘(icons.js UI, 24 viewBox)
export const SIGNAL_ICON = {
  night_repeat_transfer: "sig-night", payee_surge: "sig-person", micropay_surge: "sig-phone-pay",
  new_merchant_high_value: "sig-store", multi_line_telecom: "sig-sim",
};

export function signalLabel(item, code) {
  const r = (item.reasons || []).find((x) => x.code === code);
  if (r && r.detail && r.detail.newness_unknown && SIGNAL_KO_NEUTRAL[code]) return SIGNAL_KO_NEUTRAL[code];
  return SIGNAL_KO[code] || code;
}

export const CHANNEL_KO = {
  transfer: "계좌 이체", card: "카드 결제", micropay: "휴대폰 결제", telecom_bill: "휴대폰 요금",
  atm: "현금 찾기", income: "들어온 돈", other: "기타",
};
export const CHANNEL_ICON = {
  transfer: "bank", card: "card", micropay: "sig-phone-pay", telecom_bill: "sig-sim", atm: "cash", income: "cash", other: "cash",
};
// 차트 색 번호(css --chart-1~5, .c1~.c5). 결제 방법마다 늘 같은 색을 쓴다
export const CHANNEL_CHART = { transfer: 1, card: 2, micropay: 3, telecom_bill: 4, atm: 5, income: 5, other: 5 };

export const LEVEL = {
  none: { text: "괜찮아요", icon: "check", cls: "none" },
  caution: { text: "확인해요", icon: "warning", cls: "caution" },
  high: { text: "꼭 확인해요", icon: "stop", cls: "high" },
};

// 상담하는 곳 종류(api Counselor.kind)
export const COUNSELOR_KINDS = ["disability_center", "rights_agency", "police", "finance", "other"];
export const COUNSELOR_KIND_KO = {
  disability_center: "발달장애인지원센터", rights_agency: "장애인권익옹호기관", police: "경찰",
  finance: "금융 상담", other: "그 밖의 곳",
};
export const COUNSELOR_KIND_ICON = {
  disability_center: "building", rights_agency: "shield", police: "call", finance: "bank", other: "headset",
};

// 보낸 알림의 방법(api notices channel)
export const NOTICE_CHANNEL_KO = { sms: "문자", email: "메일", call: "전화", copy: "복사" };
export const NOTICE_CHANNEL_ICON = { sms: "chat", email: "mail", call: "call", copy: "copy" };

export const MODE_KO = { fused: "규칙 + AI 함께", rules: "규칙만", anomaly: "AI만" };
export const COUNSELING_TITLE = "상담을 도와줄 곳이 있어요.";   // guardian/policy.py NOTE_COUNSELING과 같은 문장

export const PERSONAS = [
  { value: "worker", label: "가상 근로자 (월급)" },
  { value: "benefit", label: "가상 복지급여 수급자" },
  { value: "student", label: "가상 학생 (용돈)" },
];
