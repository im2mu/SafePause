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

// 등급 배지. 아이콘은 선 아이콘(icons.js UI의 check·warning·stop, 24 viewBox 굵기 2)이다(D4: 큰 픽토그램을 섞지 않음)
export const LEVEL = {
  none: { text: "괜찮아요", icon: "check", cls: "none" },
  caution: { text: "확인해요", icon: "warning", cls: "caution" },
  high: { text: "꼭 확인해요", icon: "stop", cls: "high" },
};

// 알림 목록에 담기(담은 거래). 버튼·토스트·목록·배지 문구를 한곳에서 쓴다(RF-10·C3, 설계서 6.2)
export const FLAG_TEXT = {
  button: "알림 목록에 담기",
  undo: "담기 취소",
  toast: "알림 탭에 담았어요.",
  removed: "담은 거래에서 뺐어요.",
  list: "담은 거래",
  badge: "담음",
};

// 내가 한 거예요(오탐 바로잡기, 수정 계획 1-C). 탐지 등급은 그대로이고 표시·일부 집계만 바뀐다
export const REVIEW_TEXT = {
  button: "내가 한 거예요",
  undo: "확인 취소",
  badge: "내가 확인함",
  toast: "내가 한 거래로 표시했어요.",
  removedToast: "내가 확인한 표시를 지웠어요.",
  note: "걱정되는 거래 수에서 뺐어요.",
};

// 알린 거래 배지(직접 보낸 알림에 든 거래, 수정 계획 1-E). 날짜는 components.notifiedBadge가 붙인다
export const NOTIFIED_TEXT = "알렸어요";

// 왜 걱정되나요(수정 계획 1-D): 약속(규칙)으로 본 것 + AI가 본 것. components.aiExplain이 쓴다
export const AI_TEXT = {
  title: "왜 걱정되나요?",
  rules: "약속(규칙)으로 본 것",
  rulesNone: "약속(규칙)에 걸린 것은 없어요.",
  ai: "AI가 본 것",
  aiLearning: "거래가 30건보다 적어 AI는 아직 배우는 중이에요.",
  aiOnly: "약속(규칙)에는 걸리지 않고 AI만 찾은 거래예요.",
  aiNone: "AI가 본 정도는 아직 알 수 없어요.",
  diffLabel: "평소 내 거래와 다른 정도",
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

// 돈 보내기(보내기 전 확인 → 내 은행 앱): 카드 선택지 아이콘, 보내는 방법, 예시로 해 보기
export const DECISION_ICON = { send: "send", cancel: "stop", ask_helper: "helper" };
export const PAY_CHANNELS = [
  { value: "transfer", label: "계좌 이체", icon: "bank" },
  { value: "card", label: "가게에서 결제", icon: "card" },
  { value: "micropay", label: "휴대폰 결제", icon: "sig-phone-pay" },
];
// 칩 글의 금액·시각 안 빈칸은 줄을 바꾸지 않는 빈칸(\u00a0)이다(C13·D8: 80만 / 원, 오후 / 3시로 끊기지 않게).
// 가운뎃점 앞도 붙여 두어 줄이 바뀌면 점이 줄 앞에 오지 않는다. parts는 subParts(조각 · 조각)로 그릴 때 쓴다
export const EXAMPLES = [
  { key: "safe", label: "엄마에게 5만\u00a0원\u00a0· 오후\u00a03시", parts: ["엄마에게 5만 원", "오후 3시"], to: "엄마", amount: 50000, channel: "transfer", time: "15:00" },
  { key: "night", label: "김*호에게 30만\u00a0원\u00a0· 새벽\u00a02시", parts: ["김*호에게 30만 원", "새벽 2시"], to: "김*호", amount: 300000, channel: "transfer", time: "02:00" },
  { key: "store", label: "처음 가는 가게에서 80만\u00a0원", parts: ["처음 가는 가게에서 80만 원"], to: "새로 연 전자상가", amount: 800000, channel: "card", time: "15:00" },
];

export const MODE_KO = { fused: "규칙 + AI 함께", rules: "규칙만", anomaly: "AI만" };
export const COUNSELING_TITLE = "상담을 도와줄 곳이 있어요.";   // guardian/policy.py NOTE_COUNSELING과 같은 문장

export const PERSONAS = [
  { value: "worker", label: "근로자 (월급)" },   // 가상 인물임은 묶음 이름 '(가상 인물)'이 말한다(칸마다 쓰면 '가상 / 근로자'로 갈렸다)
  { value: "benefit", label: "복지급여 수급자" },
  { value: "student", label: "학생 (용돈)" },
];
