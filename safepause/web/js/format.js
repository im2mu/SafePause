/* 쉬운 숫자·시각 표기. 규칙은 파이썬 explain/easy_card.py와 같다(천 원·만 원 단위 반올림, '새벽 2시').
 * 목록·표의 금액은 moneyText("50,000원") 하나만 쓴다(쉬운 말 금액을 옆에 또 붙이지 않음).
 * 입력 금액 미리 보기는 amountPreview(정확한 원 단위), 시간대 이름은 bandLabel, 줄 끝 끊김 막기는 keepUnits. */
import { isApp, isMobile } from "./native.js";

export const nf = new Intl.NumberFormat("ko-KR");

/** 이 앱이 열린 곳: 앱이나 휴대폰 브라우저면 "이 휴대폰", 아니면 "이 컴퓨터". */
export function deviceWord() {
  return isApp() || isMobile() ? "이 휴대폰" : "이 컴퓨터";
}

/** 목록·표의 금액: moneyText(50000) → "50,000원", moneyText(50000, "-") → "-50,000원", moneyText(50000, "+") → "+50,000원". */
export function moneyText(value, sign = "") {
  const n = Math.round(Number(value) || 0);
  return sign ? `${sign}${nf.format(Math.abs(n))}원` : `${nf.format(n)}원`;
}

/**
 * 입력한 금액 미리 보기(돈 보내기 금액 칸 아래 줄, RF-4·C10): 정확한 원 단위 하나만 쓴다.
 * amountPreview(3500) → "3,500원". 반올림한 만 원 표기를 = 로 붙이지 않는다(3,500원이 4천 원으로 보이지 않게).
 * 숫자가 아니거나 0 이하이면 빈 글("")을 돌려준다(화면이 오류 문장을 따로 보인다).
 */
export function amountPreview(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return "";
  return moneyText(Math.round(n));
}

// 시간대(돈 흐름 분석 time_bands의 band): 앱의 시각 표기(formatTime)와 같은 말을 쓴다(수정 계획 1-E)
export const BANDS = {
  dawn: { label: "새벽", range: "밤 12시~아침 6시" },
  morning: { label: "오전", range: "아침 6시~낮 12시" },
  day: { label: "낮", range: "낮 12시~저녁 6시" },
  evening: { label: "저녁·밤", range: "저녁 6시~밤 12시" },
};

/**
 * 시간대 이름. bandLabel("dawn") → "새벽", bandLabel("dawn", {range: true}) → "새벽(밤 12시~아침 6시)".
 * 모르는 값은 그대로 돌려준다.
 */
export function bandLabel(band, { range = false } = {}) {
  const b = BANDS[band];
  if (!b) return String(band ?? "");
  return range ? `${b.label}(${b.range})` : b.label;
}

/**
 * 숫자와 단위·시각이 줄 끝에서 떨어지지 않게 그 사이 빈칸을 줄을 바꾸지 않는 빈칸으로 바꾼다(C13·D8·L8·L9).
 * keepUnits("6월 27일 새벽 4시 41분, 5만 원") → "6월 27일 새벽 4시 41분, 5만 원"
 * 화면에 보이는 글에만 쓴다(문자·메일로 보낼 글과 소리로 읽을 글에는 쓰지 않는다).
 */
export function keepUnits(text) {
  return String(text ?? "")
    .replace(/(새벽|아침|오전|낮|오후|저녁|밤) (\d{1,2}시)/g, "$1 $2")
    .replace(/(\d{1,2}시) (\d{1,2}분)/g, "$1 $2")
    .replace(/(\d{4}년) (\d{1,2}월)/g, "$1 $2")
    .replace(/(\d{1,2}월) (\d{1,2}일)/g, "$1 $2")
    .replace(/(\d[\d,.]*[억만천]?) 원/g, "$1 원")
    .replace(/(\d[\d,.]*억) (\d)/g, "$1 $2")
    .replace(/(\d[\d,.]*만) (\d[\d,.]*천)/g, "$1 $2");
}

/**
 * 메일 주소를 화면에 보일 때 @ 앞에서만 줄을 바꿀 수 있게 한다(L8: example.co / m처럼 한 글자가 남지 않게).
 * 보이는 글에만 쓴다(문자·메일 앱 주소에는 원래 값을 쓴다).
 */
export function breakableEmail(text) {
  return String(text ?? "").replace("@", "​@");
}

export function formatWon(value) {
  const n = Math.abs(Math.round(Number(value) || 0));
  if (n < 1000) return `${n}원`;
  if (n < 100000000 - 500) {             // 천 원 단위 반올림
    const k = Math.floor((n + 500) / 1000);
    const man = Math.floor(k / 10), cheon = k % 10;
    const parts = [];
    if (man) parts.push(`${nf.format(man)}만`);
    if (cheon) parts.push(`${cheon}천`);
    return `${parts.join(" ")} 원`;
  }
  if (n < 1e12 - 5000) {                 // 만 원 단위 반올림
    const m = Math.floor((n + 5000) / 10000);
    const eok = Math.floor(m / 10000), man = m % 10000;
    return man ? `${nf.format(eok)}억 ${nf.format(man)}만 원` : `${nf.format(eok)}억 원`;
  }
  const e = Math.floor((n + 5e7) / 1e8);
  const jo = Math.floor(e / 10000), eok = e % 10000;
  return eok ? `${nf.format(jo)}조 ${nf.format(eok)}억 원` : `${nf.format(jo)}조 원`;
}

export function formatTime(d) {
  const hr = d.getHours(), mi = d.getMinutes();
  let t;
  if (hr === 0) t = "밤 12시";
  else if (hr < 6) t = `새벽 ${hr}시`;
  else if (hr < 9) t = `아침 ${hr}시`;
  else if (hr < 12) t = `오전 ${hr}시`;
  else if (hr === 12) t = "낮 12시";
  else if (hr < 18) t = `오후 ${hr - 12}시`;
  else if (hr < 21) t = `저녁 ${hr - 12}시`;
  else t = `밤 ${hr - 12}시`;
  return mi ? `${t} ${mi}분` : t;
}

const WEEKDAYS = "일월화수목금토";
export function formatDate(d) {
  return `${d.getFullYear()}년 ${d.getMonth() + 1}월 ${d.getDate()}일 (${WEEKDAYS[d.getDay()]})`;
}

export function formatShortDate(d) {
  return `${d.getMonth() + 1}월 ${d.getDate()}일 ${WEEKDAYS[d.getDay()]}요일`;
}

/** "2026-06-29T20:47:25"(기기 시각) → Date. 시간대 표기가 있으면 떼고 본다. */
export function parseTs(text) {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?/.exec(text || "");
  return m ? new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0)) : null;
}

export function formatWhen(text) {
  const d = parseTs(text);
  return d ? `${formatDate(d)} ${formatTime(d)}` : (text || "");
}

/** "2026-06" → "6월"(full이면 "2026년 6월"). 돈 흐름 분석의 달 이름. */
export function formatMonth(text, full = false) {
  const m = /^(\d{4})-(\d{2})/.exec(text || "");
  if (!m) return text || "";
  return full ? `${+m[1]}년 ${+m[2]}월` : `${+m[2]}월`;
}

export function formatDay(text) {
  const d = parseTs(text);
  return d ? formatDate(d) : (text || "");
}

export function dayKey(text) {
  const d = parseTs(text);
  return d ? `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}` : "";
}

export function percent(value, digits = 1) {
  return value === null || value === undefined || Number.isNaN(value) ? "-" : `${(value * 100).toFixed(digits)}%`;
}

export function num(value, digits = 2) {
  if (value === null || value === undefined) return "-";
  return Number.isInteger(value) ? nf.format(value) : Number(value).toFixed(digits);
}

export function parseAmount(text) {
  const digits = String(text ?? "").replace(/[^\d]/g, "");
  return digits ? parseInt(digits.slice(0, 15), 10) : NaN;
}

/** 문장 끝에 마침표가 없으면 붙인다(소리로 읽을 때 쉬게). */
export function sentence(t) {
  const s = String(t || "").trim();
  return !s || /[.?!]$/.test(s) ? s : `${s}.`;
}

/** 한국어 금액 읽기(리뷰 H2: v0.1은 '80만원'을 80원으로 읽었다).
 * "800000", "800,000원", "80만", "80만 원", "1.5만", "5천", "1억 2천만", "3만 5천원" → 원 단위 정수.
 * 숫자·쉼표·공백·단위(억·만·천·원) 말고 다른 글자가 있으면 NaN(화면이 "숫자로 적어 주세요"라고 알린다). */
export function parseKoreanAmount(text) {
  const s = String(text ?? "").replace(/[\s,]/g, "").replace(/원$/, "");
  if (!s) return NaN;
  if (/^\d+$/.test(s)) return s.length > 15 ? NaN : parseInt(s, 10);
  if (!/^(?:\d+(?:\.\d+)?|[억만천백십])+$/.test(s)) return NaN;   // 숫자와 단위 말고 다른 글자가 있으면 거절
  const tokens = s.match(/\d+(?:\.\d+)?|[억만천백십]/g) || [];
  const SMALL = { 천: 1000, 백: 100, 십: 10 };
  let total = 0, section = 0, current = null, lastBig = 3, smallUnitSeen = false;   // 억=2, 만=1: 큰 단위부터
  for (let i = 0; i < tokens.length; i += 1) {
    const t = tokens[i];
    if (/\d/.test(t)) {
      if (current !== null) return NaN;                       // 숫자 두 개가 붙어 옴
      current = parseFloat(t);
      if (t.includes(".") && !(tokens[i + 1] && /[억만천백십]/.test(tokens[i + 1]))) return NaN;   // 단위 없는 소수(1.5원?) 거절
      continue;
    }
    if (SMALL[t]) { section += (current ?? 1) * SMALL[t]; current = null; smallUnitSeen = true; continue; }
    const big = t === "억" ? 2 : 1;
    if (big >= lastBig) return NaN;                            // "3만 2억"처럼 순서가 틀리면 거절
    section += current ?? 0;
    total += (section || 1) * (big === 2 ? 1e8 : 1e4);
    section = 0; current = null; lastBig = big; smallUnitSeen = false;
  }
  if (lastBig === 2 && smallUnitSeen && current === null) {
    total += section * 1e4;                                    // "1억5천" = 1억 5천만(말할 때 '만'을 빼는 습관)
  } else {
    total += section + (current ?? 0);
  }
  if (!Number.isFinite(total) || total <= 0) return NaN;
  return Math.round(total);
}
