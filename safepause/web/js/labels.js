/* 화면에 쓰는 쉬운 말 이름표. 당사자 화면에는 '주의·고위험' 대신 '확인해요·꼭 확인해요'를 쓴다
 * (전문 용어는 AI 성능 확인 표에만). 카드 문장 자체는 파이썬 explain/easy_card.py가 만든다. */
export const SIGNALS = ["night_repeat_transfer", "payee_surge", "micropay_surge", "new_merchant_high_value", "multi_line_telecom"];

export const SIGNAL_KO = {
  night_repeat_transfer: "밤에 자주 보내기",
  payee_surge: "한 사람에게 많이 보내기",
  micropay_surge: "휴대폰 결제가 많음",
  new_merchant_high_value: "새 가게에 큰 돈",
  multi_line_telecom: "휴대폰 요금이 여러 개",
};
// 이력이 짧아 '처음'인지 알 수 없을 때(newness_unknown) 쓰는 중립 이름표(카드 문구와 맞춤)
export const SIGNAL_KO_NEUTRAL = { new_merchant_high_value: "가게에 큰 돈", multi_line_telecom: "휴대폰 요금이 여러 개" };
export const SIGNAL_ICON = {
  night_repeat_transfer: "moon", payee_surge: "person", micropay_surge: "phone",
  new_merchant_high_value: "store", multi_line_telecom: "phone",
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
  transfer: "person", card: "store", micropay: "phone", telecom_bill: "phone", atm: "money", income: "money", other: "money",
};

export const LEVEL = {
  none: { text: "괜찮아요", icon: "check", cls: "none" },
  caution: { text: "확인해요", icon: "warning", cls: "caution" },
  high: { text: "꼭 확인해요", icon: "stop", cls: "high" },
};

export const DECISION_KO = { send: "그대로 했어요", cancel: "안 했어요", ask_helper: "조력자에게 물어봤어요" };
export const DECISION_ICON = { send: "money", cancel: "stop", ask_helper: "helper" };
export const ASK_NOBODY_KO = "물어보려 했지만 조력자가 없었어요";
export const DONE_KO = { transfer: "보냈어요", card: "결제했어요", micropay: "결제했어요" };
export const MODE_KO = { fused: "규칙 + AI 함께", rules: "규칙만", anomaly: "AI만" };
export const COUNSELING_TITLE = "상담을 도와줄 곳이 있어요.";   // guardian/policy.py NOTE_COUNSELING과 같은 문장
export const PRACTICE_NOTE = "연습 화면이에요. 실제로 돈이 나가지 않아요.";

export const PERSONAS = [
  { value: "worker", label: "가상 근로자 (월급)" },
  { value: "benefit", label: "가상 복지급여 수급자" },
  { value: "student", label: "가상 학생 (용돈)" },
];

export const EXAMPLES = [
  { key: "safe", label: "엄마에게 5만 원 · 오후 3시", to: "엄마", amount: 50000, channel: "transfer", time: "15:00" },
  { key: "night", label: "김*호에게 30만 원 · 새벽 2시", to: "김*호", amount: 300000, channel: "transfer", time: "02:00" },
  { key: "store", label: "처음 가는 가게에서 80만 원", to: "새로 연 전자상가", amount: 800000, channel: "card", time: "15:00" },
];
