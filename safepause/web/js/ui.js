/* 화면 도우미: DOM 만들기, 아이콘, 토스트, 시트(대화상자), 알림 읽기, 앱 설정(글자 크기·화면 모드).
 * - 서버·엔진이 준 글(받는 사람 이름 등)은 모두 textContent로 넣는다(HTML로 해석하지 않음 → XSS 차단).
 * - 시트는 열 때 배경을 inert로 만들고, 닫을 때 초점을 연 버튼으로 되돌린다(그 버튼이 없어졌으면 위 시트 제목·본문). 열린 시트는 안드로이드 뒤로 가기로 닫힌다.
 * - 시트 안의 소리로 듣기는 시트를 닫으면 멈춘다(components.speakButton이 버튼이 화면에서 떨어지는 것을 보고 멈춤).
 * - 설명 글(p)은 한 문장에 한 줄씩 보인다: h("p", {text})가 문장 끝에서 나눠 span.sent로 넣는다(data-nosplit이면 그대로).
 * - 글(p·dd·li·span·버튼 이름 등 모든 요소의 text)은 keepNodes로 넣는다: 숫자 + 단위·날짜·시각·금액은 줄 끝에서 떨어지지 않는
 *   묶음(span.nowrap), 전화번호는 하이픈 뒤에서만 줄을 바꾸는 묶음(span.tel-text), 한 글자 낱말은 뒤 낱말과·글 끝 한두 글자
 *   낱말은 앞 낱말과 한 덩어리(span.bind)로 둔다(docs/v03_typography.md 4·5). textContent는 원래 글과 같다.
 * - 버튼 이름(그림 + 글 하나)은 span.btn-label 하나로 묶는다(h): 이름이 두 줄이 되어도 그림이 첫 줄 글 앞에 붙고 줄이 고르게 나뉜다.
 */
import { PICTO, UI } from "./icons.js";

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/** h("div", {class, text, onclick, ...}, ...children). p의 text는 문장마다 한 줄(span.sent)로 나눈다. */
export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  let text;
  if (attrs) {
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") el.className = value;
      else if (key === "text") text = value;
      else if (key === "dataset") Object.assign(el.dataset, value);
      // CSP(style-src 'self')는 style 속성 문자열을 막는다. CSSOM(el.style)으로 넣으면 허용된다.
      else if (key === "style") el.style.cssText = String(value);
      else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
      else if (key === "value" && "value" in el) el.value = value;
      else if (key === "checked" || key === "disabled" || key === "selected") el[key] = Boolean(value);
      else el.setAttribute(key, value === true ? "" : String(value));
    }
  }
  if (text !== undefined) setText(el, text);
  append(el, children);
  wrapButtonLabel(el);
  return el;
}

/**
 * 버튼 이름 묶기(docs/v03_typography.md 5): .btn의 자식이 [그림(svg 또는 span.btn-ic), 글 span] 둘뿐이면 span.btn-label 하나로 묶는다.
 * 그림과 글이 따로 flex 칸이면 이름이 두 줄이 될 때 글 칸이 넓어져 그림이 왼쪽 끝으로 떨어진다. 묶으면 그림은 첫 줄 글 바로 앞에
 * 붙고(인라인), 줄은 가운데에서 고르게(balance) 나뉜다. 글 span에 클래스가 있으면(두 줄 짜임 .np-send-text 등) 그대로 둔다.
 */
function wrapButtonLabel(el) {
  if (!el.classList || !el.classList.contains("btn") || el.childNodes.length !== 2) return;
  const [ic, label] = el.childNodes;
  const isIcon = ic.nodeType === 1 && (ic.namespaceURI === SVG_NS || ic.classList.contains("btn-ic"));
  if (!isIcon || label.nodeType !== 1 || label.tagName !== "SPAN" || label.className) return;
  const box = document.createElement("span");
  box.className = "btn-label";
  box.append(ic, label);
  el.append(box);
}

// 문장 끝: 한글·닫는 괄호 뒤의 . ? ! 또는 ? ! 다음의 빈칸(1.5만·v0.3.0 같은 숫자 속 점은 나누지 않음)
const SENT_SPLIT = /(?<=[가-힣)\]][.?!]|[?!])\s+(?=\S)/;

/** 글을 문장 단위로 나눈다. "A요. B요." → ["A요.", "B요."] */
export function splitSentences(text) {
  return String(text ?? "").split(SENT_SPLIT).filter((x) => x !== "");
}

// 줄 끝에서 떨어지면 안 되는 묶음: 시각(새벽 4시 41분) · 날짜(6월 27일) · 금액(5만 원, 3만 5천 원, 63만7천원, 50,000원)
// · 전화번호 · 두 글자 낱말 둘을 가운뎃점으로 이은 말(문자·메일) · 띄어 쓴 화면 이름(알림 보내기·알림 목록: 남지만 알림 / 보내기에는처럼
// 이름이 갈려 앞말과 한 덩어리로 읽히지 않게, S010·S073. 붙은 말까지 한 묶음, 아래 name). 해(2026년)·요일((토))은 묶지 않는다
// (묶음이 길면 큰 글씨 좁은 칸에서 넘친다. 칸보다 넓은 묶음은 fitBundles가 푼다)
const KEEP_RE = /(?:새벽|아침|오전|낮|오후|저녁|밤)[ \u00a0]\d{1,2}시(?:[ \u00a0]\d{1,2}분)?|\d{1,2}월[ \u00a0]\d{1,2}일|\d[\d,.]*(?:억|만|천)?(?:[ \u00a0]?\d[\d,.]*(?:만|천))*[ \u00a0]?원|(?<![\d*])[\d*]{2,4}-[\d*]{3,4}-[\d*]{4}(?![\d*])|(?<![가-힣·])[가-힣]{1,2}·[가-힣]{1,2}(?![가-힣·])|(?<![가-힣])알림[ \u00a0](?:보내기|목록)/g;
const HANGUL_TAIL = /^[가-힣]{3,}/;
// 기관 이름처럼 긴 낱말(앞 4글자 이상 + 뒤 기관 말)은 그 사이에서 줄을 바꿀 수 있게 한다(지역발달장애인 / 지원센터).
// 낱말 끝 한두 글자(센 / 터)만 다음 줄로 밀리지 않게 한다
const LONG_NAME_RE = /[가-힣]{4,}?(?=(?:지원센터|옹호기관|보호기관|전문기관|상담소|센터|기관)[가-힣]{0,2}(?:[^가-힣]|$))/g;

/** 글 조각에 긴 기관 이름의 줄 바꿀 자리(wbr)를 넣는다. */
function softBreaks(text, out) {
  let last = 0;
  LONG_NAME_RE.lastIndex = 0;
  for (let m = LONG_NAME_RE.exec(text); m; m = LONG_NAME_RE.exec(text)) {
    const cut = m.index + m[0].length;
    out.push(document.createTextNode(text.slice(last, cut)), document.createElement("wbr"));
    last = cut;
  }
  if (last < text.length) out.push(document.createTextNode(text.slice(last)));
}

// 낱말 묶기(⑫·⑬): 한 덩어리의 글자 수 상한(한글·영문·숫자). 묶은 낱말은 줄을 바꾸지 않으므로 큰 글씨 좁은 칸에서도
// 넘치지 않게 짧게 둔다(360폭 글자 2배의 가장 좁은 문장 칸이 6.5글자쯤)
const BIND_MAX = 6;
const BIND_CAN_MAX = BIND_MAX + 2;   // ~ㄹ 수 있어요 묶음 상한(bindGroups)
// 글 끝 세 글자 낱말(않아요.·눌러요.·있어요.)의 꼬리 줄 막기: 문단의 text-wrap: pretty는 문단 안에 줄을 바꾸지 않는 묶음
// (.bind·.nowrap)이 있으면 꼬리를 다 막지 못한다(조력자 화면의 알리지 / 않아요. 문장, 글자 1.3배 160~720px 폭에서 꼬리 47곳,
// 묶음을 풀면 18곳). 묶음은 거의 모든 문장에 있으므로 끝 낱말 하나만 앞 낱말과 묶는다(bindGroups)
const TAIL3 = 3;
// 의존 명사 + 조사 한 글자(때는·수도·것은·적이·뒤에): 세 글자 끝 낱말과 묶지 않는다(알릴 / 때는 이래요.처럼 꾸미는 말과 갈리지 않게)
const BACK_LEAD = /^(?:곳|것|때|등|달|번|장|개|명|건|쯤|뿐|데|줄|중|수|뒤|후|전|적)[가-힣]$/;
// 낱말 안 문장부호(앞뒤가 빈칸이 아닌 괄호·물결·붙임표·가운뎃점·빗금·밑줄): 브라우저가 그 앞이나 뒤에서 줄을 바꿀 수 있는 자리
const PUNCT_IN = /[^\s\u00a0][([~/·\-–_)\]][^\s\u00a0]/;
const PUNCT_WORD_MAX = 16;
const SINGLE_WORD = /^[가-힣]$/;
// 앞 낱말에 붙는 한 글자 낱말(의존 명사·단위): 가는 곳·건수 등·이번 달·한 장·알릴 수·확인한 뒤·본 후·보내기 전. 뒤 낱말이 아니라
// 앞 낱말과 묶는다(뒤 낱말과 묶으면 알릴 / 수 있어요·확인한 / 뒤 이 앱을처럼 뜻 단위가 갈리고 짧은 가운데 줄이 생겼다)
const BACK_WORD = /^(?:곳|것|때|등|달|번|장|개|명|건|쯤|뿐|데|줄|중|수|뒤|후|전)$/;   // 전: 보내기 전·알림 전
// 앞 낱말 없이는 쓰지 않는 한 글자 의존 명사 + 조사 한 글자(보낸 적이·할 수도·본 것은·할 줄을): 이것도 앞 낱말과 묶는다
// (요즘 밤늦게 돈을 보낸 / 적이 있어요처럼 꾸미는 말과 의존 명사가 다른 줄로 갈리지 않게)
const BACK_PAIR = /^(?:적|것|수|줄|데|곳)(?:이|은|도|을|가|만|는|에|과|와|로)$/;   // 곳: 상담하는 곳에 / 알릴 수 있어요
const letters = (w) => (w.match(/[가-힣A-Za-z0-9]/g) || []).length;

/**
 * 글을 낱말 단위(unit)로 나눈다. unit = 빈칸 없이 이어진 조각들(묶음 + 붙은 말 포함), 사이 빈칸은 따로 둔다.
 * 조각 kind: "text"(보통 글) · "keep"(시각·날짜·띄어 쓴 금액·빈칸 없는 금액) · "dot"(문자·메일) · "tel"(전화번호) · "kw"(금액 + 붙은 말)
 * · "name"(띄어 쓴 화면 이름: 알림 보내기·알림 목록).
 * 돌려주는 값: {units: [{parts: [{kind, text}], space: 앞 빈칸}], tail: 끝 빈칸}
 */
function splitUnits(s) {
  const units = [];
  let cur = null;
  let space = "";
  const word = (kind, text) => {
    if (!text) return;
    if (!cur || space) { cur = { parts: [], space }; units.push(cur); space = ""; }
    cur.parts.push({ kind, text });
  };
  const plain = (seg) => {
    for (const t of seg.split(/([ \u00a0]+)/)) {
      if (!t) continue;
      if (/^[ \u00a0]+$/.test(t)) space += t; else word("text", t);
    }
  };
  let last = 0;
  KEEP_RE.lastIndex = 0;
  for (let m = KEEP_RE.exec(s); m; m = KEEP_RE.exec(s)) {
    if (m.index < last) continue;
    plain(s.slice(last, m.index));
    const k = m[0];
    last = m.index + k.length;
    if (/^[\d*]+-/.test(k)) { word("tel", k); continue; }
    if (k.includes("·")) { word("dot", k); continue; }
    const tail = /원$/.test(k) ? (HANGUL_TAIL.exec(s.slice(last)) || [""])[0] : "";
    if (tail) {
      const punct = (/^[.?!,)]*/.exec(s.slice(last + tail.length)) || [""])[0];
      word("kw", k + "\u0000" + tail + punct);   // \u0000 = 금액 뒤 줄 바꿀 자리(wbr)
      last += tail.length + punct.length;
      continue;
    }
    if (/^알림/.test(k)) { word("name", k); continue; }
    word("keep", k);
  }
  plain(s.slice(last));
  return { units, tail: space };
}

/**
 * 함께 둘 unit 묶음을 고른다(낱말 묶기). 돌려주는 값: [[첫 unit, 끝 unit], …]
 *  - 한 글자 낱말(열·수·내·이·더…)은 뒤 낱말과: 앱에서 열 / 수 있어요 → 앱에서 / 열 수 있어요(줄 끝에 한 글자가 홀로 남지 않게).
 *    앞 낱말에 붙는 한 글자 낱말(곳·등·달·번…, BACK_WORD)은 앞 낱말과: 처음 가는 곳 / 큰 금액 결제, 건수 등 / 11가지.
 *    ~ㄹ 수 있어요·없어요는 뒤 낱말까지 한 덩어리(BIND_CAN_MAX 글자까지): 센터에도 알릴 수 / 있어요. → 센터에도 / 알릴 수 있어요.
 *  - 글 끝 묶음이 두 글자 이하면 앞 낱말을 더한다: 불법금융 / 신고 → 불법금융 신고, 돈을 / 낼 때 → 돈을 낼 때(꼬리 줄).
 *    더할 낱말이 앞 묶음의 끝이면 합치고, 합쳐서 상한을 넘으면 앞 묶음에서 그 낱말을 떼어 온다(꼬리를 먼저 막는다)
 *  - 글 끝 낱말 하나가 세 글자(TAIL3)면 앞 낱말 하나와(앞 낱말이 묶음 끝이면 그 묶음째) 묶는다: 알리지 / 않아요. → 알리지 않아요.,
 *    늘 내가 / 눌러요. → 늘 내가 눌러요. 앞 묶음을 가르지 않고(인쇄할 수 / 있어요.는 그대로) 더 늘리지 않는다.
 *    앞 낱말이 의존 명사 + 조사(때는·수도)이거나, 묶을 덩어리 앞이 묶이지 않은 두 글자 이하 낱말(돈을 보내지 않아요.의 돈을)이면 묶지 않는다
 *  - 전화번호·금액 + 붙은 말은 묶지 않는다(그 자체로 줄 바꾸는 규칙이 있다). 묶음은 BIND_MAX 글자까지
 */
function bindGroups(units) {
  const n = units.length;
  const text = (u) => u.parts.map((p) => p.text).join("");
  // 줄바꿈 문자가 든 낱말(보낸 알림 글처럼 줄을 그대로 보이는 글)은 묶지 않는다(nowrap이 줄바꿈을 빈칸으로 바꾼다)
  const free = (i) => units[i].parts.every((p) => p.kind !== "tel" && p.kind !== "kw" && p.kind !== "name" && !/[\n\r]/.test(p.text)) && !/[\n\r]/.test(units[i].space);
  const single = (i) => units[i].parts.length === 1 && units[i].parts[0].kind === "text" && SINGLE_WORD.test(units[i].parts[0].text);
  const size = (i0, i1) => { let c = 0; for (let i = i0; i <= i1; i += 1) c += letters(text(units[i])); return c; };
  const ok = (i0, i1, max = BIND_MAX) => { for (let i = i0; i <= i1; i += 1) if (!free(i)) return false; return size(i0, i1) <= max; };
  const pair = (i) => units[i].parts.length === 1 && units[i].parts[0].kind === "text" && BACK_PAIR.test(units[i].parts[0].text);
  const back = (i) => (single(i) && BACK_WORD.test(units[i].parts[0].text)) || pair(i);
  const groups = [];
  for (let k = 0; k < n; k += 1) {
    // 괄호 안 짧은 말((학대 신고)에): 여는 괄호 낱말부터 닫는 괄호가 든 낱말까지(세 낱말 안) 한 묶음. 괄호 안에서 줄이 바뀌어
    // '(학대 / 신고),'처럼 닫는 괄호 쪽이 다음 줄 첫머리에 오지 않게
    const tk = text(units[k]);
    if (tk.startsWith("(") && !tk.includes(")")) {
      let j = k + 1;
      while (j < n && j < k + 3 && !text(units[j]).includes(")")) j += 1;
      if (j < n && text(units[j]).includes(")") && ok(k, j)) { groups.push([k, j]); k = j; continue; }
    }
    if (!single(k) && !pair(k)) continue;
    // 앞 낱말에 붙는 말(가는 곳·보낸 적이): 앞 낱말과 묶는다(앞 낱말이 이미 묶음 끝이면 그 묶음을 늘린다). 앞 낱말이 쉼표·마침표로
    // 끝나면 묶지 않는다(배우고, 뒤 30일을: 여기 뒤는 뒤 낱말을 꾸미는 말이라 앞에 붙이면 '배우고, 뒤 / 30일을'이 됐다)
    if (back(k) && k > 0 && !single(k - 1) && !/[,.!?]$/.test(text(units[k - 1]))) {
      const prev = groups.length && groups[groups.length - 1][1] === k - 1 ? groups[groups.length - 1] : null;
      let g = null;
      if (prev && ok(prev[0], k)) { prev[1] = k; g = prev; }
      else if (!prev && ok(k - 1, k)) { g = [k - 1, k]; groups.push(g); }
      if (g) {
        // ~ㄹ 수(도) 있어요·없어요: 한 덩어리 말이라 뒤 낱말까지 묶는다(알릴 수 / 있어요.처럼 끝말만 다음 줄에 남지 않게).
        // 상한은 두 글자 넉넉히(확인할 수 있어요 7글자): 칸보다 넓어지면 fitBundles가 푼다
        if (k + 1 < n && /^수/.test(units[k].parts[0].text) && /^[있없]/.test(text(units[k + 1])) && free(k + 1)
          && size(g[0], k + 1) <= BIND_CAN_MAX) { g[1] = k + 1; k += 1; }
        continue;
      }
    }
    if (!single(k) || k === n - 1) continue;
    let j = k;
    while (j < n - 1 && single(j)) j += 1;
    // 한 글자 낱말이 이어진 끝까지(열 수 있어요) → 6글자를 넘으면 바로 뒤 낱말까지(한 번 / 더 살펴봐요.)
    const pick = [[k, j], [k, k + 1]].find(([a, b]) => ok(a, b));
    if (!pick) continue;
    groups.push(pick);
    k = pick[1];
  }
  if (n >= 2 && free(n - 1)) {
    let g = groups.length && groups[groups.length - 1][1] === n - 1 ? groups[groups.length - 1] : null;
    if (!g) { g = [n - 1, n - 1]; groups.push(g); }
    while (g[0] > 0 && size(g[0], g[1]) <= 2 && ok(g[0] - 1, g[1])) {
      const prev = groups.find((q) => q !== g && q[1] === g[0] - 1);
      // 앞 묶음째 합칠 때는 8글자(BIND_CAN_MAX)까지: 6글자로 막으면 앞 묶음에서 낱말을 떼어 와 '돈 보내기 / 전 확인'처럼
      // 앞말에 붙는 말(전)이 갈렸다. 넓으면 fitBundles가 푼다
      if (prev && ok(prev[0], g[1], BIND_CAN_MAX)) { g[0] = prev[0]; groups.splice(groups.indexOf(prev), 1); continue; }
      if (prev) { prev[1] -= 1; if (prev[1] <= prev[0]) groups.splice(groups.indexOf(prev), 1); }
      g[0] -= 1;
    }
    // 세 글자 끝 낱말: 앞 낱말 하나(또는 앞 묶음째)와. 앞 묶음을 가르면(인쇄할 / 수 있어요.) 앞 낱말에 붙는 말이 갈리므로 하지 않는다.
    // 묶을 덩어리 바로 앞이 묶이지 않은 두 글자 이하 낱말이면 하지 않는다(돈을 / 보내지 않아요.처럼 그 낱말이 홀로 남지 않게)
    if (g[0] === g[1] && g[0] > 0 && size(g[0], g[1]) === TAIL3) {
      const prev = groups.find((q) => q !== g && q[1] === g[0] - 1);
      const start = prev ? prev[0] : g[0] - 1;
      const strand = start > 0 && size(start - 1, start - 1) <= 2 && !groups.some((q) => q[0] <= start - 1 && start - 1 <= q[1]);
      // 상한은 '~ㄹ 수 있어요'와 같은 8글자(살펴보지 않아요. 7글자): 넓으면 fitBundles가 푼다
      if (!strand && prev && ok(prev[0], g[1], BIND_CAN_MAX)) { g[0] = prev[0]; groups.splice(groups.indexOf(prev), 1); }
      else if (!strand && !prev && ok(g[0] - 1, g[1], BIND_CAN_MAX) && !BACK_LEAD.test(text(units[g[0] - 1]))) g[0] -= 1;
    }
  }
  return groups.filter(([x0, x1]) => x1 > x0).sort((p, q) => p[0] - q[0]);
}

/**
 * 글을 묶음 노드로(textContent는 원래 글과 같다, docs/v03_typography.md 4·5). 묶음 span은 늘 글자로 시작하고 끝난다
 * (앞뒤 빈칸을 span 안에 두지 않는다: 줄 고르기(balance)가 span 앞 빈칸에서 줄을 바꾸는 일이 있다).
 *  - span.nowrap: 시각(새벽 4시 41분)·날짜(6월 27일)·띄어 쓴 금액(3만 5천 원)·문자·메일
 *  - span.tel-text: 전화번호(하이픈 뒤에서만 줄을 바꾼다, 세 마디면 뒤 두 마디는 span.keep-word 한 덩어리)
 *  - span.keep-word: 금액 바로 뒤에 한글이 세 글자 이상 붙은 낱말(63만7천원이었어요). 한 줄에 들면 통째로 옮기고,
 *    칸보다 길 때만(아주 큰 글씨) 금액 뒤(wbr)에서 줄을 바꾼다. 7~16글자 낱말 안 문장부호(이름·계좌번호·연락처는)도 같다
 *  - 6글자까지 낱말 안 문장부호(약속(규칙)으로·비율(0~1)이에요)는 span.nowrap
 *  - span.bind(opts.bind): 한 글자 낱말 + 뒤 낱말(열 수 있어요), 글 끝 한두 글자 꼬리 + 앞 낱말(불법금융 신고), 6글자까지.
 *    버튼·칩·배지·태그·탭 안에서는 CSS가 묶음을 풀어 준다(줄 고르기 balance에 맡김)
 *  - 긴 기관 이름은 기관 말 앞(지역발달장애인 / 지원센터)에 줄 바꿀 자리(wbr)
 */
export function keepNodes(text, { bind = false } = {}) {
  const s = String(text ?? "");
  const { units, tail } = splitUnits(s);
  const groups = bind ? bindGroups(units) : [];
  const out = [];
  let buf = "";
  const flush = () => { if (buf) softBreaks(buf, out); buf = ""; };
  const span = (cls, children) => { flush(); const el = document.createElement("span"); el.className = cls; el.append(...children); out.push(el); return el; };
  // 금액 + 붙은 말(63만7천원이었어요): inline-block 한 덩어리 + 금액 뒤 줄 바꿀 자리(wbr)
  const keepWord = (t) => {
    const [amount, rest] = t.split("\u0000");
    const el = document.createElement("span");
    el.className = "keep-word";
    el.append(...(/[ \u00a0]/.test(amount) ? [Object.assign(document.createElement("span"), { className: "nowrap", textContent: amount })] : [amount]),
      document.createElement("wbr"), rest);
    return el;
  };
  const writeParts = (u) => {
    for (let pi = 0; pi < u.parts.length; pi += 1) {
      const p = u.parts[pi];
      if (p.kind === "kw") { flush(); out.push(keepWord(p.text)); }
      // 전화번호: 하이픈 뒤(wbr)에서만 줄을 바꾼다(하이픈 뒤 숫자 앞은 브라우저가 줄을 바꾸지 않아 큰 글씨에서 넘쳤다).
      // 세 마디(010-1234-5678)면 뒤 두 마디는 한 덩어리(span.keep-word): 칸이 좁으면 010- / 1234-5678로 나뉜다(앞줄을 끝까지
      // 채워 010-1234- / 5678처럼 끝 네 숫자만 홀로 내려가지 않게). 덩어리보다 좁을 때만 그 안 하이픈 뒤에서 바꾼다
      else if (p.kind === "tel") {
        const g = p.text.split(/(?<=-)/);
        const wbrs = (arr) => arr.flatMap((t, k) => (k ? [document.createElement("wbr"), t] : [t]));
        if (g.length < 3) span("tel-text", wbrs(g));
        else {
          const rest = document.createElement("span");
          rest.className = "keep-word";
          rest.append(...wbrs(g.slice(1)));
          span("tel-text", [g[0], document.createElement("wbr"), rest]);
        }
      }
      else if ((p.kind === "keep" && /[ \u00a0]/.test(p.text)) || p.kind === "dot") {
        // 바로 뒤에 붙은 말(조사 등, 같은 낱말)까지 같은 묶음에: 묶음 끝에서 Chrome이 줄을 바꿔 '새벽 2시 32분 / 에'처럼
        // 조사만 다음 줄 첫머리로 떨어졌다(묶음 경계는 keep-all이 막지 못한다). 칸보다 넓으면 fitBundles가 풀어 빈칸에서 바꾼다
        let t = p.text;
        while (pi + 1 < u.parts.length && u.parts[pi + 1].kind === "text") { pi += 1; t += u.parts[pi].text; }
        // 묶음 안 줄 바꾸지 않는 빈칸(서버 글의 U+00A0) 뒤에 wbr: 묶인 동안에는 쓰이지 않고, 칸보다 넓어 풀리면(.flow) 그 자리에서 바뀐다
        // (없으면 풀려도 바꿀 자리가 없어 '새벽 2시 32 / 분에'처럼 낱말 가운데가 잘렸다)
        span("nowrap", t.split(/(?<=\u00a0)/).flatMap((x, k) => (k ? [document.createElement("wbr"), x] : [x])));
      }
      else buf += p.text;   // 보통 글·빈칸 없는 금액(50,000원·63만7천원: 줄을 바꿀 자리가 없다)
    }
  };
  // 낱말 안 문장부호(괄호·물결·붙임표·가운뎃점·빗금)에서 줄이 바뀌지 않게(비율(0~1)이에요, 약속(규칙)으로, typing-inspection):
  //  - 6글자까지(BIND_MAX, 어느 칸에도 한 줄에 든다)는 줄을 바꾸지 않는 span.nowrap(인라인)
  //  - 7~16글자는 inline-block 한 덩어리(span.keep-word): 한 줄에 들면 통째로 옮기고, 칸보다 길 때만 안에서 줄을 바꾼다.
  //    가운뎃점으로 이은 말(이름·계좌번호·연락처는)·범위(밤 11시~새벽 6시에)는 가운뎃점·물결 뒤(wbr)에서 바꾼다(줄 첫머리에 오지 않게)
  //  - 아주 긴 낱말(파일 경로)은 그대로
  const writeUnit = (u) => {
    // 띄어 쓴 화면 이름 + 붙은 말(알림 보내기에는·알림 목록에): span.kn(낱말 전체) 안에 이름만 span.nowrap. 붙은 말까지 한 덩어리가
    // 칸보다 넓으면(320폭 2배) 아무 글자에서나 끊기므로(알림 보내기에 / 서) fitBundles가 .kn을 재서 풀고 이름 가운데 빈칸에서 바꾼다.
    // 낱말 전체를 nowrap 하나로 묶지 않는다: 그러면 문단의 text-wrap: pretty가 꼬리 줄(직접 / 보내요.)을 막지 못했다
    if (u.parts.some((p) => p.kind === "name")) {
      flush();
      const el = document.createElement("span");
      el.className = "kn";
      for (const p of u.parts) {
        if (p.kind === "name") el.append(Object.assign(document.createElement("span"), { className: "nowrap", textContent: p.text }));
        else el.append(p.text.replace("\u0000", ""));
      }
      out.push(el);
      return;
    }
    const ut = u.parts.map((p) => p.text).join("");
    if (!PUNCT_IN.test(ut) || letters(ut) > PUNCT_WORD_MAX || /[\n\r]/.test(ut) || u.parts.some((p) => p.kind === "kw" || p.kind === "tel")) { writeParts(u); return; }
    flush();
    const at = out.length;
    writeParts(u);
    flush();
    const inner = out.splice(at);
    // 이미 한 묶음(문자·메일 span.nowrap 하나)이면 그대로 둔다(겹쳐 싸지 않음)
    if (inner.length === 1 && inner[0].nodeType === 1 && inner[0].className === "nowrap") { out.push(inner[0]); return; }
    const el = document.createElement("span");
    if (letters(ut) <= BIND_MAX) {
      el.className = "nowrap";
      // 여는 괄호 앞에 줄 바꿀 자리(wbr): 묶음 안에서는 쓰이지 않고, 묶음이 칸보다 넓어 풀리면(.flow, 아주 큰 글씨 좁은 칸)
      // 약속 / (규칙)으로처럼 괄호 앞에서 바뀐다(없으면 약속(규칙)으 / 로처럼 아무 글자에서나 잘렸다)
      // 글자 + 가운뎃점(계정·)은 안쪽 nowrap: 풀렸을 때 가운뎃점이 줄 첫머리에 오지 않게('내 계정 / ·데이터' 방지)
      const dot = (t) => {
        let last = 0;
        for (const m of t.matchAll(/[가-힣A-Za-z0-9]·/g)) {
          if (m.index > last) el.append(t.slice(last, m.index));
          el.append(Object.assign(document.createElement("span"), { className: "nowrap", textContent: m[0] }));
          last = m.index + m[0].length;
        }
        if (last < t.length) el.append(t.slice(last));
      };
      for (const nd of inner) {
        if (nd.nodeType !== 3 || !/[가-힣A-Za-z0-9][(·]/.test(nd.nodeValue)) { el.append(nd); continue; }
        nd.nodeValue.split(/(?<=[가-힣A-Za-z0-9])(?=\()/).forEach((t, k) => { if (k) el.append(document.createElement("wbr")); dot(t); });
      }
    } else {
      el.className = "keep-word";
      // 줄 바꿀 자리(wbr): 가운뎃점 뒤, 물결 뒤에 한글이 올 때(밤 11시~새벽 6시에), 여는 괄호 앞(연결 / (마이데이터)은),
      // 영문 붙임표 뒤(typing- / extensions). 숫자 범위(0~1) 안은 두지 않는다
      const AT = /(?<=·)|(?<=~)(?=[가-힣])|(?<=[가-힣A-Za-z])(?=\()|(?<=[A-Za-z]-)(?=[A-Za-z])/;
      // 닫는 괄호 + 붙은 한글(…데이터)은)과 글자 + 가운뎃점(금액·)은 줄을 바꾸지 않는 묶음으로: 은 한 글자가 홀로 남거나
      // 가운뎃점이 줄 첫머리에 오지 않게(가운뎃점은 브라우저가 앞뒤에서 줄을 바꿀 수 있는 문장부호다). 가운뎃점 뒤가 덩어리 끝
      // 한두 글자면(금액·날짜) 그것까지 한 묶음(가운뎃점 뒤에서 바뀌어 날짜만 홀로 남지 않게)
      const put = (t) => {
        let last = 0;
        for (const m of t.matchAll(/\)[가-힣]+|[가-힣A-Za-z0-9]·(?:[가-힣A-Za-z0-9]{1,2}$)?/g)) {
          if (m.index > last) el.append(t.slice(last, m.index));
          el.append(Object.assign(document.createElement("span"), { className: "nowrap", textContent: m[0] }));
          last = m.index + m[0].length;
        }
        if (last < t.length) el.append(t.slice(last));
      };
      const WBR = {};
      const parts = [];
      inner.forEach((nd, idx) => {
        if (nd.nodeType === 3) nd.nodeValue.split(AT).forEach((t, k) => { if (k) parts.push(WBR); parts.push(t); });
        else parts.push(nd);
        const nx = inner[idx + 1];
        if (nx && /[·~]$/.test(nd.textContent) && /^[가-힣]/.test(nx.textContent)) parts.push(WBR);
      });
      // 마지막 줄 바꿀 자리 뒤가 두 글자 이하면(금액·시간대· / 처음) 그 자리를 빼고 앞 조각과 붙인다
      const lastW = parts.lastIndexOf(WBR);
      const tailText = parts.slice(lastW + 1).map((x) => (typeof x === "string" ? x : x.textContent)).join("");
      if (lastW > 0 && letters(tailText) <= 2) {
        parts.splice(lastW, 1);
        if (typeof parts[lastW - 1] === "string" && typeof parts[lastW] === "string") parts.splice(lastW - 1, 2, parts[lastW - 1] + parts[lastW]);
      }
      for (const x of parts) {
        if (x === WBR) el.append(document.createElement("wbr"));
        else if (typeof x === "string") put(x);
        else el.append(x);
      }
    }
    out.push(el);
  };
  // 낱말 묶음(span.bind) 안: 시각·날짜·띄어 쓴 금액·문자·메일은 span.nowrap을 그대로 둔다(버튼 안에서 묶음이 풀려도 끊기지 않게)
  // 묶음 안 글: 글자 + 가운뎃점(계정·)은 안쪽 nowrap(묶음이 풀려도 가운뎃점이 줄 첫머리에 오지 않게)
  const pushText = (kids, t) => {
    let last = 0;
    for (const m of t.matchAll(/[가-힣A-Za-z0-9]·/g)) {
      if (m.index > last) kids.push(document.createTextNode(t.slice(last, m.index)));
      kids.push(Object.assign(document.createElement("span"), { className: "nowrap", textContent: m[0] }));
      last = m.index + m[0].length;
    }
    if (last < t.length) kids.push(document.createTextNode(t.slice(last)));
  };
  const bindChildren = (g) => {
    const kids = [];
    let t = "";
    for (let j = g[0]; j <= g[1]; j += 1) {
      if (j > g[0]) t += units[j].space;
      for (const p of units[j].parts) {
        const pt = p.text.replace("\u0000", "");
        if ((p.kind === "keep" && /[ \u00a0]/.test(pt)) || p.kind === "dot") {
          if (t) pushText(kids, t);
          t = "";
          kids.push(Object.assign(document.createElement("span"), { className: "nowrap", textContent: pt }));
        } else t += pt;
      }
    }
    if (t) pushText(kids, t);
    return kids;
  };
  let gi = 0;
  for (let i = 0; i < units.length; i += 1) {
    const g = groups[gi];
    buf += units[i].space;   // 낱말 앞 빈칸은 앞 글과 같은 조각에(줄이 바뀌는 자리, 빈칸만 든 조각을 되도록 만들지 않는다)
    if (g && g[0] === i) {
      span("bind", bindChildren(g));
      i = g[1];
      gi += 1;
      continue;
    }
    writeUnit(units[i]);
  }
  buf += tail;
  flush();
  // 묶음 사이 빈칸은 빈칸만 든 글 조각으로 둔다. 예전에는 묶음 끝·처음 글자 하나를 그 조각으로 옮겼는데([꼭 확인까지]는), 묶음이 칸에
  // 꼭 맞으면 옮긴 글자가 다음 줄로 밀려 낱말 가운데에서 줄이 바뀌었고('꼭 확인까지 / 는'), fitBundles는 옮긴 글자를 뺀 폭만 재서 풀지 못했다
  return out;
}

// 글을 그대로(묶음 없이) 넣는 요소: 글만 담을 수 있는 요소와 SVG 글
const PLAIN_TAGS = new Set(["OPTION", "TITLE", "TEXTAREA", "SCRIPT", "STYLE"]);

/**
 * 글을 넣는다. p(문단)는 문장마다 span.sent(한 줄)로 나누고(data-nosplit이 있으면 나누지 않음), 숫자·낱말 묶음을 지킨다(keepNodes).
 * p가 아닌 요소(dd·li·td·span·버튼 등)도 묶음을 지킨다(문장으로 나누지는 않음). option·textarea 등과 SVG 글은 그대로 넣는다.
 */
export function setText(el, text) {
  const s = text === null || text === undefined ? "" : String(text);
  if (el.tagName !== "P") {
    if (PLAIN_TAGS.has(el.tagName) || el.namespaceURI === SVG_NS) { el.textContent = s; return el; }
    const nodes = keepNodes(s, { bind: true });
    if (nodes.length <= 1 && (!nodes.length || nodes[0].nodeType === 3)) { el.textContent = s; return el; }
    // 묶음 노드는 span 하나에 담는다: flex 칸인 요소(버튼·칩·배지·섹션 제목 등)에 그대로 넣으면 조각마다 따로 flex 칸이 된다
    const box = document.createElement("span");
    box.append(...nodes);
    el.replaceChildren(box);
    return el;
  }
  const parts = el.hasAttribute("data-nosplit") ? [s] : splitSentences(s);
  if (parts.length < 2) { el.replaceChildren(...keepNodes(s, { bind: true })); return el; }
  // 문장 사이 빈칸은 span 끝에 남겨 둔다(복사·소리로 읽기에서 문장이 붙지 않게)
  el.replaceChildren(...parts.map((part, i) => {
    const sp = document.createElement("span");
    sp.className = "sent";
    sp.append(...keepNodes(i < parts.length - 1 ? `${part} ` : part, { bind: true }));
    return sp;
  }));
  return el;
}

export function append(el, children) {
  for (const child of [children].flat(Infinity)) {
    if (child === null || child === undefined || child === false || child === "") continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export function fill(el, ...children) {
  el.replaceChildren();
  return append(el, children);
}

const SVG_NS = "http://www.w3.org/2000/svg";

function svgFrom(markup, viewBox, cls, stroke) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", viewBox);
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", stroke);
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  if (cls) svg.setAttribute("class", cls);
  // 아이콘 문자열은 이 앱 소스(icons.js)의 고정 값뿐이다(외부 입력 아님)
  const doc = new DOMParser().parseFromString(`<svg xmlns="${SVG_NS}">${markup}</svg>`, "image/svg+xml");
  for (const node of Array.from(doc.documentElement.childNodes)) svg.append(document.importNode(node, true));
  return svg;
}

/**
 * 화면용 선 아이콘(24x24, 굵기 2). 이름이 UI에 없으면 빈 자리(span.ic)를 돌려준다.
 * check·warning·stop·person 같은 픽토그램 이름도 UI의 선 버전으로 그린다(D4: 선 아이콘 체계 하나).
 */
export function icon(name, cls = "") {
  const markup = UI[name];
  if (!markup) return h("span", { class: "ic", "aria-hidden": "true" });
  return svgFrom(markup, "0 0 24 24", cls, "2");
}

/** 쉬운 말 카드 픽토그램(64x64, v0.1 그림). 돈 보내기 확인 카드 본문의 큰 그림에만 쓴다. */
export function picto(name, cls = "picto") {
  const markup = PICTO[name];
  return markup ? svgFrom(markup, "0 0 64 64", cls, "4") : null;
}

// ---- 묶음 안전장치: 칸보다 넓은 묶음은 푼다 ---------------------------------------------
// 시각·날짜·금액·낱말 묶음(span.nowrap·span.bind)은 한 줄에 들면 통째로 옮기지만, 묶음 하나가 그 글 칸(가장 가까운 블록)보다
// 넓으면(아주 큰 글씨·좁은 화면·기기마다 다른 글꼴) 줄을 못 바꿔 화면 밖으로 넘친다. 그런 묶음만 .flow로 풀어 보통 글처럼
// 줄을 바꾼다(들어가는 묶음은 그대로라 평소 모양은 같다). 글이 바뀔 때·창 크기나 글자 크기가 바뀔 때 다시 본다(watchBundles)
const INLINE_DISPLAY = new Set(["inline", "inline-block", "contents"]);
function blockInner(el) {
  let p = el.parentElement;
  while (p && INLINE_DISPLAY.has(getComputedStyle(p).display)) p = p.parentElement;
  if (!p) return Infinity;
  const s = getComputedStyle(p);
  return p.clientWidth - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight);
}

// 묶음이나 묶음을 감싼 상자가 그 바깥 상자의 안쪽 오른쪽 끝을 넘는가: 감싼 칸이 묶음 폭만큼 넓어진 경우(내용 폭 칸),
// 묶음을 품은 이름표(배지·태그)가 통째로 줄 칸을 넘는 경우도 잡는다. 일부러 왼쪽·오른쪽으로 내민 상자(음수 여백)는
// 넘침으로 보지 않는다. 가로 스크롤 칸(표·시트 본문)에 닿으면 거기까지만 본다(그 안의 넘침은 그 칸이 스크롤로 보여 준다)
function sticksOut(el) {
  let child = el;
  for (let p = el.parentElement; p && p !== document.body; child = p, p = p.parentElement) {
    const s = getComputedStyle(p);
    if (s.display !== "inline" && s.display !== "contents") {
      const cs = getComputedStyle(child);
      const pos = cs.position;
      if (pos !== "absolute" && pos !== "fixed" && !(parseFloat(cs.marginRight) < 0)) {
        const inner = p.getBoundingClientRect().right - parseFloat(s.paddingRight) - parseFloat(s.borderRightWidth);
        if (child.getBoundingClientRect().right > inner + 0.5) return true;
      }
    }
    if (s.overflowX !== "visible" && s.overflowX !== "clip") return false;
  }
  return false;
}

// .kn(화면 이름 + 붙은 말, keepNodes): 칸보다 넓어 두 줄로 끊겼으면 푼다
const BUNDLES = ".nowrap, .bind, .keep-word, .kn";
/** 인라인 요소가 두 줄 이상에 걸쳤는가. 꾸밈 없는 인라인은 한 줄에서도 조각(자식 글·묶음)마다 사각형을 주므로 개수가 아니라 줄 높이로 본다 */
function splitLines(el) {
  const rs = el.getClientRects();
  for (let i = 1; i < rs.length; i += 1) if (Math.abs(rs[i].top - rs[0].top) > rs[0].height / 2) return true;
  return false;
}
/** 버튼 이름 첫머리의 .kn이 그림 옆에 들지 않아 그림만 첫 줄에 홀로 남았는가(320폭 2배 좁은 카드의 [그림] / 알림 목록에 / 담기). 그러면 푼다 */
function iconAlone(el) {
  const lab = el.closest(".btn-label");
  const ic = lab && lab.firstElementChild;
  if (!ic || !(ic.namespaceURI === SVG_NS || ic.classList.contains("btn-ic")) || !lab.textContent.trimStart().startsWith(el.textContent)) return false;
  const r = el.getClientRects()[0];
  const ir = ic.getBoundingClientRect();
  return Boolean(r && ir.height > 0 && Math.abs((r.top + r.bottom) / 2 - (ir.top + ir.bottom) / 2) > r.height / 2);
}

/** 칸보다 넓거나 상자 밖으로 나간 묶음에 .flow를 붙인다. reset이면 먼저 모두 떼고 다시 잰다(창·글자 크기가 바뀐 뒤). */
export function fitBundles(root = document.body, reset = false) {
  if (!root) return;
  if (reset) for (const el of root.querySelectorAll(".flow")) el.classList.remove("flow");
  const wide = [];
  const els = root.matches && root.matches(BUNDLES) ? [root, ...root.querySelectorAll(BUNDLES)] : root.querySelectorAll(BUNDLES);
  for (const el of els) {
    if (el.classList.contains("flow") || el.closest(".sr-only, .flow")) continue;   // 화면 읽기 전용 글(1px 칸)·이미 푼 묶음 안
    const w = el.offsetWidth;   // 레이아웃 폭(시트가 올라오는 동안의 transform과 무관)
    if (w > 0 && (w > blockInner(el) + 0.5 || sticksOut(el) || (el.classList.contains("kn") && (splitLines(el) || iconAlone(el))))) wide.push(el);
  }
  for (const el of wide) el.classList.add("flow");   // 다 잰 뒤에 바꾼다(재고 바꾸기를 번갈아 하지 않게)
  fitLabels(root);
}

// ---- 두 줄 이름표 폭 맞추기 --------------------------------------------------------------
// 태그·배지(inline-flex: 그림 + 글) 안 글이 두 줄로 접히면 브라우저는 상자를 실제 줄 폭이 아니라 칸 끝까지 늘린다.
// 그래서 '휴대폰 / 소액결제 급증' 오른쪽에 글 폭만큼 빈 칸이 생기고, 바로 위 한 줄 태그와 폭이 들쭉날쭉해진다.
// 두 줄 이상인 이름표만 글 칸 폭을 가장 긴 줄 폭으로 줄인다(한 줄 이름표는 그대로라 평소 모양은 같다).
// 맞춘 표시(data-fit-w)는 다시 잴 때마다 먼저 떼고 잰다(글자 크기·창 크기가 바뀌면 줄 수도 바뀐다)
const LABELS = ".tag, .badge";
function fitLabels(root) {
  const host = root.closest ? root.closest(LABELS) : null;   // 이름표 안 글만 바뀐 경우: 그 이름표부터 다시
  const scope = host || root;
  const boxes = scope.matches && scope.matches(LABELS) ? [scope, ...scope.querySelectorAll(LABELS)] : [...scope.querySelectorAll(LABELS)];
  if (!boxes.length) return;
  const old = [...scope.querySelectorAll("[data-fit-w]")];
  if (scope.hasAttribute && scope.hasAttribute("data-fit-w")) old.push(scope);
  for (const el of old) { el.style.maxWidth = ""; el.removeAttribute("data-fit-w"); }
  const todo = [];
  for (const box of boxes) {
    // 줄일 칸: [그림, 글 span]·[글 span]이면 글 span, 글 마디가 이름표 바로 안에 있으면 이름표 자신
    const last = box.lastElementChild;
    const own = !last || last.namespaceURI === SVG_NS || box.lastChild !== last;
    const target = own ? box : last;
    const height = target.offsetHeight;
    if (!height) continue;   // 숨겨진 칸
    const s = getComputedStyle(target);
    const lh = parseFloat(s.lineHeight) || parseFloat(s.fontSize) * 1.3;
    const inner = height - (own ? parseFloat(s.paddingTop) + parseFloat(s.paddingBottom) + parseFloat(s.borderTopWidth) + parseFloat(s.borderBottomWidth) : 0);
    if (inner < lh * 1.5) continue;   // 한 줄
    let right = -Infinity;
    for (const n of own ? [...box.childNodes].filter((x) => x.namespaceURI !== SVG_NS) : [target]) {
      const range = document.createRange();
      if (n.nodeType === 1) range.selectNodeContents(n); else range.selectNode(n);
      for (const r of range.getClientRects()) if (r.width > 0) right = Math.max(right, r.right);
    }
    const rect = target.getBoundingClientRect();
    if (!(right > rect.left)) continue;
    // 가장 긴 줄의 오른쪽 끝까지 + (이름표 자신이면) 오른쪽 안쪽 여백·테두리. 1px은 소수점 폭 때문에 줄이 하나 더 생기지 않게
    const w = Math.ceil(right - rect.left + (own ? parseFloat(s.paddingRight) + parseFloat(s.borderRightWidth) : 0)) + 1;
    if (w < rect.width - 1) todo.push([target, w]);
  }
  for (const [el, w] of todo) { el.style.maxWidth = `${w}px`; el.setAttribute("data-fit-w", ""); }   // 다 잰 뒤에 바꾼다
}

/** 화면 글이 바뀌거나(hidden·open 포함) 창·글자 크기가 바뀌면 fitBundles를 다시 부른다. main.js가 한 번 켠다. */
export function watchBundles() {
  if (typeof MutationObserver !== "function") return;
  // 새로 들어온 부분(과 보이게 된 부분)만 잰다: 긴 목록을 그릴 때마다 화면 전체를 다시 재지 않게
  new MutationObserver((records) => {
    const roots = new Set();
    for (const r of records) {
      if (r.type === "attributes") roots.add(r.target);
      else for (const n of r.addedNodes) roots.add(n.nodeType === 1 ? n : n.parentElement);
    }
    for (const el of roots) if (el && el.isConnected) fitBundles(el);
  }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden", "open"] });
  let frame = 0;
  const refit = () => {
    window.cancelAnimationFrame(frame);
    frame = window.requestAnimationFrame(() => fitBundles(document.body, true));
  };
  window.addEventListener("resize", refit);
  // 글자 크기만 바뀔 때(앱을 연 채 기기 글자 크기를 바꾸면 WebView textZoom만 바뀐다): 창 크기는 그대로라 resize가 오지 않아
  // 1배 때 잰 묶음·이름표 폭이 남았다(배지가 '걱정되 / 는 거래'처럼 낱말 가운데에서 잘린 채). 1em 크기의 보이지 않는 칸이
  // 커지거나 작아지는 것을 보고 다시 잰다(처음 한 번 알림은 넘긴다)
  if (typeof ResizeObserver === "function") {
    const em = document.createElement("span");
    em.setAttribute("aria-hidden", "true");
    em.style.cssText = "position: absolute; top: 0; left: 0; width: 1em; height: 1em; visibility: hidden; pointer-events: none;";
    document.body.append(em);
    let seen = false;
    new ResizeObserver(() => { if (seen) refit(); seen = true; }).observe(em);
  }
  fitBundles(document.body, true);
}

// ---- 알림(스크린리더) -------------------------------------------------------
export function announce(message) {
  const el = $("#announcer");
  if (!el) return;
  el.textContent = "";
  window.setTimeout(() => { el.textContent = message; }, 60);
}

// ---- 토스트 -----------------------------------------------------------------
let toastTimer = 0;
/** 잠깐 보이는 알림 글. 문장이 여럿이면 한 문장에 한 줄(p → span.sent, C4). 문장 수만큼 조금 더 오래 보인다. */
export function toast(message, kind = "") {
  const root = $("#toast-root");
  if (!root) return;
  window.clearTimeout(toastTimer);
  const n = splitSentences(message).length;
  fill(root, h("div", { class: `toast ${kind}`.trim(), role: kind === "error" ? "alert" : "status" }, h("p", { text: message })));
  toastTimer = window.setTimeout(() => root.replaceChildren(), (kind === "error" ? 5200 : 3200) + Math.max(0, n - 1) * 1500);
}

// ---- 시트(아래에서 올라오는 창; 넓은 화면은 가운데 창) -------------------------------
const openSheets = [];

function setInert(on) {
  for (const el of $$("#app > *:not(#sheet-root)")) {
    if (on) { el.setAttribute("inert", ""); el.setAttribute("aria-hidden", "true"); } else { el.removeAttribute("inert"); el.removeAttribute("aria-hidden"); }
  }
}

/** 초점을 줄 수 있는 상태인지(붙어 있고, 꺼지지 않았고, 숨겨지지 않음). */
function focusable(el) {
  return Boolean(el && el !== document.body && el.isConnected && typeof el.focus === "function"
    && !el.disabled && !el.closest("[inert]") && !el.closest("[hidden]"));
}

/**
 * 시트를 닫은 뒤 초점을 돌려줄 곳(FE-04·FN-07): 연 버튼 → (그 버튼이 없어졌거나 꺼졌으면) 아직 열린 위 시트의 제목 → 본문.
 * 초점이 body로 빠지지 않게 한다.
 */
function restoreFocus(returnFocus) {
  if (focusable(returnFocus)) { returnFocus.focus(); return; }
  const top = openSheets[openSheets.length - 1];
  if (top) {
    const t = $(".focus-target", top.el) || top.el;
    t.focus({ preventScroll: true });
    return;
  }
  const main = $("#main");
  if (main) main.focus({ preventScroll: true });
}

/**
 * 시트를 연다. build(close)는 시트 안의 노드를 돌려준다.
 * opts: {label, dismissible(기본 true), className, onClose, initialFocus}
 * 돌려주는 값: {close, el}
 */
export function openSheet(build, opts = {}) {
  const root = $("#sheet-root");
  const returnFocus = document.activeElement;
  const dismissible = opts.dismissible !== false;
  const sheet = h("div", {
    class: `sheet ${opts.className || ""}`.trim(), role: "dialog", "aria-modal": "true",
    "aria-label": opts.label || null, tabindex: "-1",
  });
  const overlay = h("div", { class: "overlay" }, sheet);
  let closed = false;
  const entry = { close: () => close("api"), dismissible, el: sheet, onEscape: opts.onEscape };

  function close(reason = "api") {
    if (closed) return;
    closed = true;
    overlay.remove();
    const i = openSheets.indexOf(entry);
    if (i >= 0) openSheets.splice(i, 1);
    if (!openSheets.length) { setInert(false); document.body.style.overflow = ""; }
    document.removeEventListener("keydown", onKey, true);
    if (typeof opts.onClose === "function") opts.onClose(reason);
    // onClose가 다른 시트를 열었으면 그 시트가 초점을 가진다
    if (openSheets.length && openSheets[openSheets.length - 1].el.contains(document.activeElement)) return;
    restoreFocus(returnFocus);
  }

  function onKey(e) {
    if (openSheets[openSheets.length - 1] !== entry) return;
    if (e.key === "Escape") {
      e.preventDefault();
      if (dismissible) close("escape");
      else if (typeof opts.onEscape === "function") opts.onEscape();
      return;
    }
    if (e.key !== "Tab") return;
    const items = $$("button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex='-1'].focus-target", sheet)
      .filter((x) => x.offsetParent !== null || x === document.activeElement);
    if (!items.length) { e.preventDefault(); sheet.focus(); return; }
    const first = items[0], last = items[items.length - 1];
    // 초점이 시트 밖(body 등)에 있으면 시트 안으로 끌어온다(본문으로 바로 가기 링크로 나가지 않게, FE-04)
    if (!sheet.contains(document.activeElement)) { e.preventDefault(); (e.shiftKey ? last : first).focus(); return; }
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }

  overlay.addEventListener("click", (e) => { if (e.target === overlay && dismissible) close("scrim"); });
  append(sheet, build(close));
  root.append(overlay);
  openSheets.push(entry);
  setInert(true);
  document.body.style.overflow = "hidden";
  document.addEventListener("keydown", onKey, true);
  const target = (opts.initialFocus && $(opts.initialFocus, sheet)) || $(".focus-target", sheet) || sheet;
  window.requestAnimationFrame(() => target.focus());
  entry.close = () => close("api");
  return { close: () => close("api"), el: sheet };
}

/** 안드로이드 뒤로 가기: 맨 위 시트를 닫으면 true. */
export function closeTopSheet() {
  const top = openSheets[openSheets.length - 1];
  if (!top) return false;
  if (top.dismissible) top.close();
  else if (typeof top.onEscape === "function") top.onEscape();   // 닫을 수 없는 시트(저장 안 한 입력 등): 시트가 정한 동작
  return true;   // 닫을 수 없는 시트는 뒤로 가기로 앞 화면에 넘어가지 않게 삼킨다
}

export function closeAllSheets() {
  while (openSheets.length) openSheets[openSheets.length - 1].close();
}

/** 확인 창. 안전한 선택(취소)에 먼저 초점을 둔다. */
export function confirmSheet({ title, lines = [], confirmText, cancelText = "아니요", danger = false }) {
  return new Promise((resolve) => {
    let result = false;
    openSheet((close) => [
      h("h2", { class: "sheet-title focus-target", tabindex: "-1", text: title }),
      // 확인 창의 설명은 한 문단(문장마다 한 줄). 이름처럼 따로 둘 줄은 배열로: [[이름], ["문장."]]
      paragraphs(lines).map((t) => h("p", { class: "sheet-sub", text: t })),
      h("div", { class: "sheet-actions" },
        h("button", { type: "button", class: `btn big block ${danger ? "danger" : "primary"}`, text: confirmText,
          onclick: () => { result = true; close(); } }),
        h("button", { type: "button", class: "btn big block", "data-cancel": "1", text: cancelText, onclick: () => close() })),
    ], { label: title, initialFocus: "[data-cancel]", onClose: () => resolve(result) });
  });
}

/**
 * 버튼을 잠시 하는 중 상태로(두 번 누름 방지). disabled를 쓰지 않는다: 누른 버튼이 꺼지면 초점이 body로 빠지고,
 * 그 안에서 연 확인 시트가 닫힐 때 초점을 돌려줄 곳이 없어진다(FE-04·FN-07). 대신 aria-busy·aria-disabled로 막는다.
 */
export async function busy(btn, fn) {
  if (!btn) return fn();
  if (btn.getAttribute("aria-busy") === "true") return undefined;   // 두 번 누름 방지
  btn.setAttribute("aria-busy", "true");
  btn.setAttribute("aria-disabled", "true");
  try { return await fn(); } finally {
    btn.removeAttribute("aria-busy");
    btn.removeAttribute("aria-disabled");
  }
}

export function skeleton(n = 3) {
  return h("div", { "aria-hidden": "true" }, Array.from({ length: n }, () => h("div", { class: "skeleton sk-block" })));
}

export function emptyState(iconName, title, text) {
  return h("div", { class: "empty" }, icon(iconName), h("b", { text: title }), text ? h("p", { text }) : null);
}

// ---- 준비 중 기능 --------------------------------------------------------------
/** 준비 중 기능에 늘 붙이는 문장. */
export const SOON_TEXT = "정식 버전에서 열려요.";

/** 준비 중 배지(목록·시트 제목 옆). */
export function soonBadge() {
  return h("span", { class: "soon", text: "준비 중" });
}

/**
 * 준비 중 기능 안내 시트. 동작하는 척하지 않고, 정식 버전에서 할 일을 비활성으로 보여 준다.
 * opts: {icon, title, lines[], steps?: [{title, sub?, options?: []}], action?: "연결하기", extra?: Node | (close) => Node}
 * - action이 있으면 "연결하기(준비 중)" 비활성 버튼을 둔다((준비 중)은 끊기지 않는 묶음이라 큰 글씨에서 괄호 앞에서 줄을 바꾼다).
 * - extra는 지금 쓸 수 있는 다른 방법(버튼 등)을 넣는 자리다.
 * 돌려주는 값: openSheet와 같은 {close, el}
 */
/** 문장 목록을 문단 글로: ["가.", "나."] → ["가. 나."], [["가.", "나."], ["다."]] → ["가. 나.", "다."]. */
export function paragraphs(lines) {
  const list = (lines || []).filter((x) => x !== null && x !== undefined && x !== "");
  if (list.some(Array.isArray)) return list.map((x) => (Array.isArray(x) ? x.filter(Boolean).join(" ") : String(x))).filter(Boolean);
  return list.length ? [list.join(" ")] : [];
}

export function comingSoonSheet({ icon: ic = "info", title, lines = [], steps = [], action = "", extra = null } = {}) {
  return openSheet((close) => [
    h("div", { class: "soon-head" }, h("span", { class: "soon-icon" }, icon(ic)), soonBadge()),
    h("h2", { class: "sheet-title focus-target", tabindex: "-1", text: title }),
    // 설명은 한 문단(문장마다 한 줄). 뜻이 다른 문단으로 나누려면 lines에 배열을 넣는다: [["가.", "나."], ["다."]]
    lines.length ? h("div", { class: "soon-lines" }, paragraphs(lines).map((t) => h("p", { text: t }))) : null,
    steps.length ? h("ol", { class: "soon-steps", "aria-label": "정식 버전에서 하는 순서" }, steps.map((st, i) => h("li", { class: "soon-step", "aria-disabled": "true" },
      h("span", { class: "soon-step-no", "aria-hidden": "true", text: String(i + 1) }),
      h("div", { class: "soon-step-main" },
        h("b", { text: st.title }),
        st.sub ? h("p", { class: "muted", text: st.sub }) : null,
        st.options && st.options.length ? h("div", { class: "soon-options" }, st.options.map((o) => h("span", { class: "chip off", "aria-disabled": "true", text: o }))) : null)))) : null,
    h("div", { class: "notice" }, icon("info"), h("p", { text: SOON_TEXT })),
    typeof extra === "function" ? extra(close) : extra,
    h("div", { class: "sheet-actions" },
      // 글은 연결하기(준비 중) 그대로, (준비 중)은 끊기지 않는 묶음: 큰 글씨에서 괄호 앞에서 줄이 바뀐다(계좌 연결하기 / (준비 중))
      action ? h("button", { type: "button", class: "btn primary big block", disabled: true },
        h("span", null, action, h("wbr"), h("span", { class: "nowrap", text: "(준비 중)" }))) : null,
      h("button", { type: "button", class: "btn big block", text: "닫기", onclick: () => close() })),
  ], { label: title });
}

// ---- 탭(segmented) -------------------------------------------------------------
/**
 * 한 줄 탭. items: [{value, label, icon?, count?}], onChange(value)는 탭을 바꿀 때 불린다.
 * opts: {label(탭 묶음 이름), controls(바뀌는 영역 id)}
 * 돌려주는 값: {el, set(value)}  (set은 onChange를 부르지 않는다)
 */
export function segTabs(items, active, onChange, { label = "보기", controls = null } = {}) {
  const el = h("div", { class: "seg-tabs", role: "tablist", "aria-label": label });
  const buttons = items.map((it) => h("button", {
    type: "button", class: "seg-tab", role: "tab", "data-v": it.value, "aria-controls": controls,
    onclick: () => choose(it.value, false),
  }, it.icon ? icon(it.icon) : null, h("span", { text: it.label }),
  it.count === undefined || it.count === null ? null : h("span", { class: "seg-count", text: String(it.count) })));
  append(el, buttons);
  el.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight" && e.key !== "Home" && e.key !== "End") return;
    const i = buttons.indexOf(document.activeElement);
    if (i < 0) return;
    e.preventDefault();
    const n = buttons.length;
    const next = e.key === "Home" ? 0 : e.key === "End" ? n - 1 : (i + (e.key === "ArrowRight" ? 1 : -1) + n) % n;
    choose(buttons[next].dataset.v, true);
  });
  function set(value) {
    for (const b of buttons) {
      const on = b.dataset.v === String(value);
      b.setAttribute("aria-selected", on ? "true" : "false");
      b.tabIndex = on ? 0 : -1;
    }
  }
  function choose(value, focus) {
    const changed = buttons.some((b) => b.dataset.v === String(value) && b.getAttribute("aria-selected") !== "true");
    set(value);
    if (focus) { const b = buttons.find((x) => x.dataset.v === String(value)); if (b) b.focus(); }
    if (changed && typeof onChange === "function") onChange(value);
  }
  set(active);
  return { el, set };
}

// ---- 앱 설정: 글자 크기·화면 모드(이 휴대폰·이 컴퓨터에만 저장) ---------------------------------
const PREFS = {
  font: { key: "safepause.font", values: ["m", "l", "xl"], fallback: "m" },        // 보통·크게·아주 크게
  theme: { key: "safepause.theme", values: ["auto", "light", "dark"], fallback: "auto" },   // 자동·밝게·어둡게
};
const THEME_BG = { light: "#f2f4f6", dark: "#101013" };

/** getPref("font") → "m"|"l"|"xl", getPref("theme") → "auto"|"light"|"dark". 못 읽으면 기본값. */
export function getPref(name) {
  const p = PREFS[name];
  if (!p) return null;
  let v = null;
  try { v = localStorage.getItem(p.key); } catch (e) { v = null; }
  return p.values.includes(v) ? v : p.fallback;
}

/** 설정을 저장하고 바로 적용한다. 저장을 못 해도(사생활 보호 창 등) 이번 화면에는 적용한다. */
export function setPref(name, value) {
  const p = PREFS[name];
  if (!p || !p.values.includes(value)) return false;
  try { localStorage.setItem(p.key, value); } catch (e) { /* 저장 못 해도 적용은 한다 */ }
  applyPrefs({ [name]: value });
  return true;
}

/** 시작할 때 main.js가 부른다. html[data-font]·html[data-theme]를 맞춘다. */
export function applyPrefs(over = {}) {
  const root = document.documentElement;
  const font = over.font || getPref("font");
  const theme = over.theme || getPref("theme");
  if (font === "m") delete root.dataset.font; else root.dataset.font = font;
  if (document.body) fitBundles(document.body, true);   // 글자 크기가 바뀌면 묶음 폭도 바뀐다
  if (theme === "auto") delete root.dataset.theme; else root.dataset.theme = theme;
  for (const meta of $$('meta[name="theme-color"]')) {
    const darkMedia = /dark/.test(meta.getAttribute("media") || "");
    meta.setAttribute("content", theme === "auto" ? THEME_BG[darkMedia ? "dark" : "light"] : THEME_BG[theme]);
  }
  // 안드로이드 앱: 앱 설정의 밝게·어둡게가 기기 설정과 달라도 위아래 시스템 막대 색을 맞춘다(AND-04, 옛 APK에는 함수가 없음)
  try {
    const native = window.SafePauseNative;
    if (native && typeof native.setThemeMode === "function") native.setThemeMode(theme);
  } catch (e) { /* 막대 색만 못 맞춘다 */ }
}
