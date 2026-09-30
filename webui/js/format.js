/* 쉬운 숫자·시각 표기. 규칙은 파이썬 explain/easy_card.py와 같다(천 원·만 원 단위 반올림, '새벽 2시'). */
export const nf = new Intl.NumberFormat("ko-KR");

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
