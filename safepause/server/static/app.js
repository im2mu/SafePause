/* SafePause 화면 스크립트. 외부 라이브러리·CDN 없음.
 * - 서버 글(거래 상대 이름 등)은 모두 textContent로 넣는다(HTML로 해석하지 않음).
 * - 상태를 바꾸는 요청에는 X-SafePause: 1 머리글을 붙인다(서버가 요구).
 * - 어떤 경우에도 보내기를 막지 않는다. 실제 송금은 없다(연습 화면).
 */
(() => {
  "use strict";

  // ---- 고정 값 ------------------------------------------------------------
  const ICONS = new Set(["moon", "money", "question", "phone", "store", "person",
    "warning", "check", "stop", "helper", "ear"]);
  const COUNSELING_TITLE = "상담을 도와줄 곳이 있어요.";  // guardian/policy.py NOTE_COUNSELING과 같은 문장
  const SIGNALS = ["night_repeat_transfer", "payee_surge", "micropay_surge",
    "new_merchant_high_value", "multi_line_telecom"];
  const SIGNAL_KO = {
    night_repeat_transfer: "밤에 자주 보내기",
    payee_surge: "한 사람에게 많이 보내기",
    micropay_surge: "휴대폰 결제가 많음",
    new_merchant_high_value: "새 가게에 큰 돈",
    multi_line_telecom: "휴대폰 요금이 여러 개",
  };
  // 이력이 짧아 '처음'인지 알 수 없을 때(newness_unknown) 쓰는 중립 태그. 카드 문구(easy_card)와 맞춘다.
  const SIGNAL_KO_NEUTRAL = {
    new_merchant_high_value: "가게에 큰 돈",
    multi_line_telecom: "휴대폰 요금이 여러 개",
  };
  function signalLabel(item, code) {
    const r = (item.reasons || []).find((x) => x.code === code);
    if (r && r.detail && r.detail.newness_unknown && SIGNAL_KO_NEUTRAL[code]) return SIGNAL_KO_NEUTRAL[code];
    return SIGNAL_KO[code] || code;
  }
  const SIGNAL_ICON = {
    night_repeat_transfer: "moon", payee_surge: "person", micropay_surge: "phone",
    new_merchant_high_value: "store", multi_line_telecom: "phone",
  };
  const CHANNEL_KO = {
    transfer: "계좌 이체", card: "카드 결제", micropay: "휴대폰 결제", telecom_bill: "휴대폰 요금",
    atm: "현금 찾기", income: "들어온 돈", other: "기타",
  };
  const CHANNEL_ICON = {
    transfer: "person", card: "store", micropay: "phone", telecom_bill: "phone",
    atm: "money", income: "money", other: "money",
  };
  // 당사자 화면에는 쉬운 말만 쓴다(주의·고위험 같은 말은 ⑥ 성능 확인 표에만)
  const LEVEL = {
    none: { text: "괜찮아요", icon: "check" },
    caution: { text: "확인해요", icon: "warning" },
    high: { text: "꼭 확인해요", icon: "stop" },
  };
  const DECISION_KO = { send: "그대로 했어요", cancel: "안 했어요", ask_helper: "조력자에게 물어봤어요" };
  const ASK_NOBODY_KO = "물어보려 했지만 조력자가 없었어요";   // 물어본 조력자 0명(서버 기록 asked=0)
  // 동의가 꺼져 있어 살펴보지 않았을 때의 결과 문장(거래 방법별 동사)
  const DONE_KO = { transfer: "보냈어요", card: "결제했어요", micropay: "결제했어요" };
  const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;   // 서버와 같은 한도(5MB)
  const DECISION_ICON = { send: "money", cancel: "stop", ask_helper: "helper" };
  const MODE_KO = { fused: "규칙 + AI 함께", rules: "규칙만", anomaly: "AI만" };
  const EXAMPLES = {
    safe: { to: "엄마", amount: 50000, channel: "transfer", time: "15:00" },
    night: { to: "김*호", amount: 300000, channel: "transfer", time: "02:00" },
    store: { to: "새로 연 전자상가", amount: 800000, channel: "card", time: "15:00" },
  };
  const TABS = ["consent", "txns", "practice", "cards", "helpers", "eval", "wipe"];
  const PAGE_SIZE = 50;
  const MAX_AMOUNT = 10000000000;

  const state = {
    txnFilter: "all",
    txnItems: [],
    txnShown: 0,
    payeesLoaded: false,
    pending: null,       // 카드에서 고르기를 기다리는 거래(check 요청 + 정해진 시각)
    lastCheck: null,
    cardHelperText: "",  // 카드의 조력자 안내(소리로 듣기용)
    returnFocus: null,
  };

  // ---- DOM 도우미 ----------------------------------------------------------
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    if (attrs) {
      for (const [key, value] of Object.entries(attrs)) {
        if (value === null || value === undefined || value === false) continue;
        if (key === "class") el.className = value;
        else if (key === "text") el.textContent = value;
        else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
        else el.setAttribute(key, value === true ? "" : String(value));
      }
    }
    for (const child of children.flat(Infinity)) {
      if (child === null || child === undefined || child === false) continue;
      el.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return el;
  }

  // ---- 픽토그램(인라인 SVG) --------------------------------------------------
  const iconCache = new Map();

  function loadIcon(name) {
    if (!ICONS.has(name)) return Promise.resolve(null);
    if (!iconCache.has(name)) {
      const p = fetch(`/static/icons/${name}.svg`)
        .then((r) => (r.ok ? r.text() : ""))
        .then((text) => {
          const doc = new DOMParser().parseFromString(text, "image/svg+xml");
          const svg = doc.documentElement;
          if (!svg || svg.nodeName.toLowerCase() !== "svg") return null;
          svg.querySelector("title")?.remove();
          svg.setAttribute("aria-hidden", "true");
          svg.setAttribute("focusable", "false");
          return svg;
        })
        .catch(() => null);
      iconCache.set(name, p);
    }
    return iconCache.get(name);
  }

  function fillIcon(el) {
    const name = el.dataset.icon;
    el.setAttribute("aria-hidden", "true");
    loadIcon(name).then((svg) => {
      if (svg && el.dataset.icon === name) el.replaceChildren(document.importNode(svg, true));
    });
  }

  function fillIcons(root = document) { $$("[data-icon]", root).forEach(fillIcon); }

  function icon(name, extra = "") {
    const el = h("span", { class: `icon ${extra}`.trim(), "data-icon": name });
    fillIcon(el);
    return el;
  }

  // ---- 서버 호출 ------------------------------------------------------------
  class ApiError extends Error {
    constructor(status, message) { super(message); this.status = status; }
  }

  async function api(method, path, body, isForm = false) {
    const opts = { method, headers: { Accept: "application/json" }, cache: "no-store" };
    if (method !== "GET") opts.headers["X-SafePause"] = "1";
    if (body !== undefined) {
      if (isForm) opts.body = body;
      else { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    }
    let res;
    try { res = await fetch(path, opts); } catch (e) {
      throw new ApiError(0, "SafePause 프로그램에 연결할 수 없어요. 프로그램이 켜져 있는지 확인해 주세요.");
    }
    let data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    if (!res.ok) {
      const detail = data && typeof data.detail === "string" ? data.detail : `문제가 생겼어요 (${res.status})`;
      throw new ApiError(res.status, detail);
    }
    return data;
  }

  // ---- 알림 문구 ------------------------------------------------------------
  function setStatus(el, content, kind = "") {
    el.className = "status" + (kind ? ` ${kind}` : "");
    if (content instanceof Node) el.replaceChildren(content);
    else el.textContent = content || "";
  }

  function announce(message) {
    const el = $("#announcer");
    el.textContent = "";
    window.setTimeout(() => { el.textContent = message; }, 50);
  }

  function isConsentError(err) { return err && err.status === 403 && /동의/.test(err.message); }

  function goConsentButton() {
    return h("button", { type: "button", class: "btn", onclick: () => selectTab("consent", true) },
      icon("person"), h("span", { text: "① 동의로 가기" }));
  }

  function showError(el, err) {
    if (isConsentError(err)) {
      setStatus(el, h("div", null, h("p", { text: err.message }), goConsentButton()), "error");
    } else {
      setStatus(el, err.message || String(err), "error");
    }
  }

  // ---- 쉬운 숫자·시각 (easy_card.py와 같은 규칙) ------------------------------
  const nf = new Intl.NumberFormat("ko-KR");

  function formatWon(value) {
    let n = Math.abs(Math.round(Number(value) || 0));
    if (n < 1000) return `${n}원`;
    if (n < 100000000 - 500) {           // 천 원 단위 반올림
      const k = Math.floor((n + 500) / 1000);
      const man = Math.floor(k / 10), cheon = k % 10;
      const parts = [];
      if (man) parts.push(`${nf.format(man)}만`);
      if (cheon) parts.push(`${cheon}천`);
      return `${parts.join(" ")} 원`;
    }
    if (n < 1e12 - 5000) {               // 만 원 단위 반올림
      const m = Math.floor((n + 5000) / 10000);
      const eok = Math.floor(m / 10000), man = m % 10000;
      return man ? `${nf.format(eok)}억 ${nf.format(man)}만 원` : `${nf.format(eok)}억 원`;
    }
    const e = Math.floor((n + 5e7) / 1e8);
    const jo = Math.floor(e / 10000), eok = e % 10000;
    return eok ? `${nf.format(jo)}조 ${nf.format(eok)}억 원` : `${nf.format(jo)}조 원`;
  }

  function formatTime(d) {
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
  function formatDate(d) {
    return `${d.getFullYear()}년 ${d.getMonth() + 1}월 ${d.getDate()}일 (${WEEKDAYS[d.getDay()]})`;
  }

  function parseTs(text) {  // "2026-06-29T20:47:25" (이 컴퓨터 시각)
    const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?/.exec(text || "");
    return m ? new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0)) : null;
  }

  function formatWhen(text) {
    const d = parseTs(text);
    return d ? `${formatDate(d)} ${formatTime(d)}` : (text || "");
  }

  function formatDay(text) {
    const d = parseTs(text);
    return d ? formatDate(d) : (text || "");
  }

  function percent(value) {
    return value === null || value === undefined ? "-" : `${(value * 100).toFixed(1)}%`;
  }

  function num(value, digits = 2) {
    if (value === null || value === undefined) return "-";
    return Number.isInteger(value) ? nf.format(value) : Number(value).toFixed(digits);
  }

  // AI 학습 안내: span = 앞쪽 학습 구간 거래 수, rows = 실제 학습한 거래 수(모델 버전의 숫자).
  // 평소 기준이 아직 없는 맨 앞 거래는 학습에서 빼므로 rows가 더 적을 수 있다(docs/model_card.md §2).
  function learnedText(span, rows) {
    if (Number.isInteger(rows) && rows > 0 && rows < span) {
      return `AI는 앞쪽 거래 ${nf.format(span)}건 가운데 ${nf.format(rows)}건으로 평소 모습을 배웠어요. `
        + `맨 앞 ${nf.format(span - rows)}건은 비교할 평소가 없어서 뺐어요.`;
    }
    return `AI는 앞쪽 거래 ${nf.format(span)}건으로 평소 모습을 배웠어요.`;
  }

  function learnedRows(span, rows) {
    if (Number.isInteger(rows) && rows > 0 && rows < span) {
      return `${nf.format(span)}건 (맨 앞 ${nf.format(span - rows)}건은 비교할 평소가 없어서 빼고 ${nf.format(rows)}건으로 배움)`;
    }
    return `${nf.format(span)}건`;
  }

  // ---- 소리로 듣기(Web Speech API) -------------------------------------------
  // 이 컴퓨터 안의 한국어 음성(localService)만 쓴다. 온라인 음성은 읽을 글(받는 사람·금액)을
  // 밖의 서버로 보내므로 쓰지 않는다. 쓸 음성이 없으면 '소리로 듣기' 버튼을 숨긴다.
  const canSpeak = "speechSynthesis" in window && typeof window.SpeechSynthesisUtterance === "function";
  const SPEECH_NOTE_NO_API = "이 브라우저에서는 '소리로 듣기'를 쓸 수 없어요.";
  let koVoice = null;
  document.body.classList.add("no-speech");   // 음성을 찾을 때까지 숨김

  function pickVoice() {
    if (canSpeak) {
      let voices = [];
      try { voices = window.speechSynthesis.getVoices() || []; } catch (e) { voices = []; }
      koVoice = voices.find((v) => v.localService === true && /^ko/i.test(v.lang || "")) || null;
    }
    document.body.classList.toggle("no-speech", !koVoice);
    const note = $("#speech-note");
    if (!note) return;
    if (!canSpeak) note.textContent = SPEECH_NOTE_NO_API;   // 그 밖(한국어 음성 없음)은 index.html 문구
    note.hidden = Boolean(koVoice);
  }

  pickVoice();   // Web Speech API가 없어도 안내는 보여 준다
  if (canSpeak) {
    // 음성 목록은 늦게 채워진다
    if (typeof window.speechSynthesis.addEventListener === "function") {
      window.speechSynthesis.addEventListener("voiceschanged", pickVoice);
    } else {
      window.speechSynthesis.onvoiceschanged = pickVoice;
    }
  }

  function speak(text) {
    if (!canSpeak || !text || !koVoice) return;   // 이 컴퓨터 음성이 없으면 읽지 않는다
    const synth = window.speechSynthesis;
    synth.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.voice = koVoice;
    u.lang = koVoice.lang;
    u.rate = 0.9;
    synth.speak(u);
  }

  function stopSpeaking() { if (canSpeak) window.speechSynthesis.cancel(); }

  function speakButton(getText, label = "소리로 듣기") {
    return h("button", {
      type: "button", class: "btn speak",
      onclick: () => speak(typeof getText === "function" ? getText() : getText),
    }, icon("ear"), h("span", { text: label }));
  }

  // ---- 탭 ------------------------------------------------------------------
  const loaders = {
    consent: loadConsent, txns: loadTxns, practice: loadPractice, cards: loadCards,
    helpers: loadHelpers, eval: () => null, wipe: () => null,
  };

  function selectTab(name, focusTab = false) {
    if (!TABS.includes(name)) name = "consent";
    for (const id of TABS) {
      const on = id === name;
      const tab = $(`#tab-${id}`);
      tab.setAttribute("aria-selected", on ? "true" : "false");
      tab.tabIndex = on ? 0 : -1;
      $(`#panel-${id}`).hidden = !on;
    }
    if (focusTab) $(`#tab-${name}`).focus();
    if (location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
    stopSpeaking();
    Promise.resolve(loaders[name]()).catch(() => null);
  }

  function initTabs() {
    const tabs = $$('[role="tab"]');
    tabs.forEach((tab, i) => {
      tab.addEventListener("click", () => selectTab(tab.dataset.panel));
      tab.addEventListener("keydown", (e) => {
        let j = null;
        if (e.key === "ArrowRight" || e.key === "ArrowDown") j = (i + 1) % tabs.length;
        else if (e.key === "ArrowLeft" || e.key === "ArrowUp") j = (i - 1 + tabs.length) % tabs.length;
        else if (e.key === "Home") j = 0;
        else if (e.key === "End") j = tabs.length - 1;
        if (j === null) return;
        e.preventDefault();
        selectTab(tabs[j].dataset.panel, true);
      });
    });
    window.addEventListener("hashchange", () => selectTab(location.hash.slice(1)));
    selectTab(location.hash.slice(1) || "consent");
  }

  async function refreshStatusLine() {
    try {
      const [c, s, hs] = await Promise.all([
        api("GET", "/api/consent"), api("GET", "/api/data/summary"), api("GET", "/api/helpers"),
      ]);
      const parts = [
        `거래 살펴보기 ${c.monitoring ? "켜짐" : "꺼짐"}`,
        `조력자 알림 ${c.helper_alerts ? "켜짐" : "꺼짐"}`,
        `저장된 거래 ${nf.format(s.count)}건`,
        `조력자 ${hs.length}명`,
      ];
      $("#status-line").textContent = `지금 상태: ${parts.join(" · ")}`;
    } catch (e) {
      $("#status-line").textContent = e.message;
    }
  }

  // ---- ① 동의 --------------------------------------------------------------
  function renderConsent(c) {
    $$(".switch[data-consent]").forEach((btn) => {
      const on = Boolean(c[btn.dataset.consent]);
      btn.setAttribute("aria-checked", on ? "true" : "false");
      $(".switch-text", btn).textContent = on ? "켜짐" : "꺼짐";
    });
    $$('input[name="given_by"]').forEach((r) => { r.checked = r.value === (c.given_by || "self"); });
    $("#consent-updated").textContent = c.updated_at
      ? `마지막으로 바꾼 때: ${formatWhen(c.updated_at)}`
      : "아직 아무것도 켜지 않았어요. 모두 꺼져 있어요.";
  }

  async function loadConsent() {
    try { renderConsent(await api("GET", "/api/consent")); } catch (e) { showError($("#consent-status"), e); }
  }

  async function toggleConsent(btn) {
    const key = btn.dataset.consent;
    const next = btn.getAttribute("aria-checked") !== "true";
    const title = $(`#${btn.getAttribute("aria-labelledby")}`).textContent;
    btn.setAttribute("aria-busy", "true");
    try {
      renderConsent(await api("PUT", "/api/consent", { [key]: next }));
      const msg = next ? `${title}: 켰어요.` : `${title}: 껐어요. 바로 멈췄어요.`;
      setStatus($("#consent-status"), msg, "ok");
      announce(msg);
      state.payeesLoaded = false;
      if (key === "monitoring" && !next) clearAnalysisViews();
      refreshStatusLine();
    } catch (e) {
      showError($("#consent-status"), e);
    } finally {
      btn.removeAttribute("aria-busy");
    }
  }

  // 동의 없이는 볼 수 없는 분석 결과(거래 목록·받는 사람 자동완성·알림 카드·내 거래 확인)를 화면에서 지운다
  function clearAnalysisViews() {
    state.txnItems = [];
    state.txnShown = 0;
    state.payeesLoaded = false;
    for (const sel of ["#txn-list", "#payee-list", "#cards-list", "#eval-mine-result"]) {
      const el = $(sel);
      if (el) el.replaceChildren();
    }
    for (const sel of ["#txn-status", "#cards-status", "#eval-mine-status"]) {
      const el = $(sel);
      if (el) setStatus(el, "");
    }
    const more = $("#btn-more");
    if (more) more.hidden = true;
  }

  async function changeGivenBy(value) {
    try {
      renderConsent(await api("PUT", "/api/consent", { given_by: value }));
      setStatus($("#consent-status"), value === "self" ? "나(본인)가 동의했어요." : "법정대리인이 동의했어요.", "ok");
    } catch (e) { showError($("#consent-status"), e); }
  }

  // ---- ② 내 거래 ------------------------------------------------------------
  async function loadSummary() {
    try {
      const s = await api("GET", "/api/data/summary");
      $("#data-summary").textContent = s.count
        ? `저장된 거래 ${nf.format(s.count)}건 (${formatDay(s.first_ts)} ~ ${formatDay(s.last_ts)})`
        : "저장된 거래가 없어요. 연습용 거래를 불러오거나 파일을 올려 주세요.";
    } catch (e) {
      $("#data-summary").textContent = e.message;
    }
  }

  function txnRow(item) {
    const t = item.txn;
    const d = parseTs(t.ts);
    const out = t.direction === "out";
    const lv = LEVEL[item.level] || LEVEL.none;
    const aiReason = (item.reasons || []).some((r) => String(r.code).startsWith("anomaly:"));
    return h("li", { class: `txn level-${item.level}` },
      icon(CHANNEL_ICON[t.channel] || "money"),
      h("div", null,
        h("div", { class: "txn-who", text: t.counterparty || "(이름 없음)" }),
        h("div", { class: "txn-when", text: d ? `${formatDate(d)} ${formatTime(d)}` : t.ts }),
        h("div", { class: "txn-how", text: CHANNEL_KO[t.channel] || t.channel })),
      h("div", { class: "txn-amount" },
        h("div", { text: `${out ? "나감" : "들어옴"} ${formatWon(t.amount)}` }),
        h("div", { class: "small", text: `${nf.format(t.amount)}원` })),
      (item.level !== "none" || item.practice || (t.label && t.label !== "normal"))
        ? h("div", { class: "txn-extra" },
          item.level !== "none"
            ? h("span", { class: `level-badge level-${item.level}` }, icon(lv.icon), h("span", { text: lv.text }))
            : null,
          (item.signals || []).map((code) => h("span", { class: "tag" },
            icon(SIGNAL_ICON[code] || "warning"), h("span", { text: signalLabel(item, code) }))),
          aiReason ? h("span", { class: "tag", text: "평소와 달라요 (AI)" }) : null,
          item.practice ? h("span", { class: "tag", text: "보내기 연습" }) : null,
          (t.label && t.label !== "normal")
            ? h("span", { class: "tag", text: `연습용 정답: ${SIGNAL_KO[t.label] || t.label}` })
            : null)
        : null);
  }

  function showMoreTxns() {
    const list = $("#txn-list");
    const next = state.txnItems.slice(state.txnShown, state.txnShown + PAGE_SIZE);
    list.append(...next.map(txnRow));
    state.txnShown += next.length;
    const more = $("#btn-more");
    more.hidden = state.txnShown >= state.txnItems.length;
    more.textContent = `더 보기 (${nf.format(state.txnItems.length - state.txnShown)}건 남음)`;
  }

  function updatePayeeList(items) {
    const names = [];
    for (const it of items) {
      const t = it.txn;
      if (t.direction === "out" && t.channel === "transfer" && t.counterparty && !names.includes(t.counterparty)) {
        names.push(t.counterparty);
      }
      if (names.length >= 30) break;
    }
    $("#payee-list").replaceChildren(...names.map((n) => h("option", { value: n })));
    state.payeesLoaded = true;
  }

  async function loadTxns() {
    loadSummary();
    const status = $("#txn-status");
    const list = $("#txn-list");
    list.setAttribute("aria-busy", "true");
    setStatus(status, "불러오는 중이에요…");
    try {
      const data = await api("GET", `/api/transactions?level=${state.txnFilter}`);
      state.txnItems = data.items;
      state.txnShown = 0;
      list.replaceChildren();
      const s = data.summary;
      const model = data.model.fitted
        ? learnedText(data.model.train_count, data.model.train_rows)
        : "거래가 30건보다 적어서 AI 없이 규칙으로만 살펴봐요.";
      setStatus(status, `모두 ${nf.format(data.count)}건 · 괜찮아요 ${s.none}건 · 확인해요 ${s.caution}건 · `
        + `꼭 확인해요 ${s.high}건. ${model}`);
      if (!data.items.length) {
        list.append(h("li", { class: "txn", text: data.count ? "고른 조건에 맞는 거래가 없어요." : "저장된 거래가 없어요." }));
      }
      showMoreTxns();
      if (state.txnFilter === "all") updatePayeeList(data.items);
    } catch (e) {
      list.replaceChildren();
      $("#btn-more").hidden = true;
      showError(status, e);
    } finally {
      list.removeAttribute("aria-busy");
    }
  }

  async function loadSample() {
    const btn = $("#btn-sample");
    const seed = parseInt($("#sample-seed").value || "1", 10);
    const body = {
      persona: $("#sample-persona").value,
      seed: Number.isFinite(seed) && seed >= 0 ? seed : 1,
      scenarios: $("#sample-scenarios").checked,
    };
    btn.disabled = true;
    try {
      const r = await api("POST", "/api/data/sample", body);
      const mixed = Object.values(r.scenario_labels || {}).reduce((a, b) => a + b, 0);
      const msg = `${r.persona_name}의 가상 거래 ${nf.format(r.count)}건을 불러왔어요.`
        + (r.scenarios ? ` 걱정되는 거래 ${mixed}건을 섞었어요.` : " 걱정되는 거래는 섞지 않았어요.");
      setStatus($("#data-status"), msg, "ok");
      announce(msg);
      refreshStatusLine();
      await loadTxns();
    } catch (e) {
      showError($("#data-status"), e);
    } finally {
      btn.disabled = false;
    }
  }

  async function uploadFile() {
    const out = $("#upload-report");
    const file = $("#upload-file").files[0];
    if (!file) { setStatus(out, "먼저 CSV 파일을 골라 주세요.", "error"); return; }
    if (file.size > MAX_UPLOAD_BYTES) { setStatus(out, "파일이 너무 커요(5MB까지).", "error"); return; }
    const form = new FormData();
    form.append("file", file, file.name);
    const mapping = $("#upload-mapping").value.trim();
    if (mapping) form.append("mapping", mapping);
    const btn = $("#btn-upload");
    btn.disabled = true;
    setStatus(out, "읽는 중이에요…");
    try {
      const r = await api("POST", "/api/data/upload", form, true);
      const rep = r.report;
      setStatus(out, h("div", null,
        h("p", { text: `${nf.format(rep.loaded)}건을 읽었어요. 못 읽은 줄은 ${rep.skipped}개예요.` }),
        rep.warnings && rep.warnings.length
          ? h("details", { open: true }, h("summary", { text: `알아 두기 ${rep.warnings.length}가지` }),
            h("ul", null, rep.warnings.map((w) => h("li", { text: w }))))
          : null), "ok");
      announce(`${rep.loaded}건을 읽었어요.`);
      refreshStatusLine();
      await loadTxns();
    } catch (e) {
      showError(out, e);
    } finally {
      btn.disabled = false;
    }
  }

  // ---- ③ 보내기 연습(안전 정지) ----------------------------------------------
  async function loadPractice() {
    if (state.payeesLoaded) return;
    try {
      const d = await api("GET", "/api/transactions?level=all&limit=400");
      updatePayeeList(d.items);
    } catch (e) {
      // 동의가 없으면 목록 없이 쓴다(전에 불러 둔 받는 사람 이름도 남기지 않음)
      if (isConsentError(e)) $("#payee-list").replaceChildren();
    }
  }

  function parseAmount(text) {
    const digits = String(text).replace(/[^\d]/g, "");
    return digits ? parseInt(digits, 10) : NaN;
  }

  function radioValue(name) {
    const el = $(`input[name="${name}"]:checked`);
    return el ? el.value : "";
  }

  function formError(message, selector) {
    const err = $("#pay-error");
    err.textContent = message;
    err.hidden = false;
    if (selector) $(selector).focus();
  }

  function updateAmountEasy() {
    const n = parseAmount($("#pay-amount").value);
    $("#pay-amount-easy").textContent = Number.isFinite(n) && n > 0 ? `= ${formatWon(n)}` : "";
  }

  function fillExample(key) {
    const ex = EXAMPLES[key];
    if (!ex) return;
    $("#pay-to").value = ex.to;
    $("#pay-amount").value = nf.format(ex.amount);
    $$('input[name="channel"]').forEach((r) => { r.checked = r.value === ex.channel; });
    $$('input[name="time"]').forEach((r) => { r.checked = r.value === ex.time; });
    $("#pay-to-id").value = "";
    updateAmountEasy();
    $("#pay-error").hidden = true;
    $("#btn-pay").focus();
    announce("칸을 채웠어요. 보내기를 눌러 보세요.");
  }

  async function onPay(e) {
    e.preventDefault();
    $("#pay-error").hidden = true;
    const to = $("#pay-to").value.trim();
    const amount = parseAmount($("#pay-amount").value);
    if (!to) { formError("받는 사람을 적어 주세요.", "#pay-to"); return; }
    if (!Number.isFinite(amount) || amount <= 0) { formError("금액을 숫자로 적어 주세요.", "#pay-amount"); return; }
    if (amount > MAX_AMOUNT) { formError("금액이 너무 커요.", "#pay-amount"); return; }

    const req = { to, amount, channel: radioValue("channel") || "transfer", to_id: $("#pay-to-id").value.trim() };
    const time = radioValue("time");
    if (time) req.time = time;

    const btn = $("#btn-pay");
    btn.disabled = true;
    $("#pay-result").hidden = true;
    try {
      const r = await api("POST", "/api/safepause/check", req);
      // 고르기(decide)는 check에서 정한 시각 그대로 보낸다
      // check가 정한 연습 거래 id도 담는다(다시 보내도 서버가 두 번 적지 않게)
      state.pending = {
        id: r.pending.id, to: req.to, amount: req.amount, channel: req.channel, to_id: req.to_id, ts: r.pending.ts,
      };
      state.lastCheck = r;
      if (r.card) openCard(r);
      else await decide("send");   // 걱정 없음 → 바로 "보냈어요"
    } catch (err) {
      if (isConsentError(err)) showUncheckedResult(req);
      else formError(err.message);
    } finally {
      btn.disabled = false;
    }
  }

  function showUncheckedResult(req) {
    // 동의가 없으면 살펴보지 않는다. 그래도 막지 않는다.
    const box = $("#pay-result");
    const done = DONE_KO[req.channel] || "보냈어요";
    const lines = [`${formatWon(req.amount)}을 ${done}.`, "거래 살펴보기가 꺼져 있어서 SafePause는 확인하지 않았어요."];
    const note = "연습 화면이에요. 실제로 돈이 나가지 않아요.";
    box.className = "result";
    box.replaceChildren(
      h("p", { class: "result-title" }, icon("check", "icon-lg"), h("span", { text: `${done} (연습)` })),
      ...lines.map((t) => h("p", { text: t })),
      h("p", null, h("strong", { text: note })),
      speakButton([`${done} (연습).`, ...lines, note].join(" ")),
      goConsentButton());
    box.hidden = false;
    box.focus();
  }

  // 카드 모달
  function openCard(r) {
    const card = r.card;
    const lv = LEVEL[card.level] || LEVEL.caution;
    const modal = $("#card-modal");
    $(".modal-box", modal).className = `modal-box level-${card.level}`;
    const badge = $("#card-level");
    badge.className = `level-badge level-${card.level}`;
    badge.replaceChildren(icon(lv.icon), h("span", { text: lv.text }));
    $("#card-pictos").replaceChildren(...card.pictograms.map((p) => icon(p)));
    $("#card-title").textContent = card.title;
    $("#card-lines").replaceChildren(...card.lines.map((line) => h("li", { text: line })));
    $("#card-question").textContent = card.question;

    // 고르기 전에 누가 알게 되는지 보여 준다(자동 알림 + '조력자에게 물어볼래요'를 고를 때)
    const plan = r.notify_plan_preview;
    const note = $("#card-helper-note");
    const notes = [];
    if (plan && plan.note_to_person && (plan.notices.length || plan.excluded_conflict.length)) {
      notes.push(plan.note_to_person);
    }
    notes.push(askPreviewText(askCandidates(r)));
    state.cardHelperText = notes.join(" ");   // 소리로 듣기용(줄바꿈 대신 띄어쓰기)
    note.replaceChildren(icon("helper"), h("span", null,
      notes.map((t, i) => [i ? [" ", h("br")] : null, t])));
    note.hidden = false;
    $("#card-error").hidden = true;
    $("#card-close").hidden = true;

    $("#card-choices").replaceChildren(...card.choices.map((c) => h("button", {
      type: "button", class: "btn", "data-decision": c.decision,
      onclick: () => (c.decision === "ask_helper" ? openAskStep(r) : chooseDecision(c.decision)),
    }, icon(DECISION_ICON[c.decision] || "check"), h("span", { text: c.label }))));
    $("#card-choices").hidden = false;
    $("#card-ask").hidden = true;

    state.returnFocus = document.activeElement;
    setBackgroundInert(true);
    modal.hidden = false;
    document.body.style.overflow = "hidden";
    $("#card-title").focus();   // 선택지에 바로 초점을 두지 않는다(실수로 고르지 않게)
  }

  // '조력자에게 물어볼래요' 2단계: 물어볼 사람을 당사자가 고른다(S37)
  function askCandidates(r) {
    return (r && r.ask_helper_preview && r.ask_helper_preview.candidates) || [];
  }

  function namesText(names) {
    return names.length <= 2 ? names.join(", ") : `${names[0]} 외 ${names.length - 1}명`;
  }

  function askPreviewText(cands) {
    const selectable = cands.filter((c) => !c.conflict);
    const picked = selectable.filter((c) => c.default || c.auto).map((c) => c.name);
    const autoNames = selectable.filter((c) => c.auto).map((c) => c.name);   // 자동 알림 대상은 뺄 수 없음
    const others = selectable.filter((c) => !c.auto);
    if (!cands.length) return "물어볼 수 있는 조력자가 없어요. ⑤ 조력자에서 정할 수 있어요.";
    if (picked.length) {
      let more = "";
      if (others.length && !autoNames.length) more = " 다음 화면에서 바꿀 수 있어요.";
      else if (others.some((c) => c.default)) more = ` 다음 화면에서 ${namesText(autoNames)} 말고는 바꿀 수 있어요.`;
      else if (others.length) more = " 다음 화면에서 다른 사람을 더할 수 있어요.";
      return `'조력자에게 물어볼래요'를 고르면 ${namesText(picked)}에게 물어봐요.${more}`;
    }
    if (selectable.length) return "'조력자에게 물어볼래요'를 고르면, 물어볼 사람을 다음 화면에서 골라요.";
    return "지금은 물어볼 수 있는 조력자가 없어요. 조력자가 돈을 받는 사람이에요.";
  }

  // 배열·null이 섞인 자식 목록을 펼쳐서 넣는다(replaceChildren은 배열을 글자로 바꿔 버림)
  function fillWith(el, ...children) {
    el.replaceChildren(...children.flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false));
  }

  // 물어볼 수 없는 까닭(조력자 없음, 또는 모두 돈을 받는 사람)
  function askNobodyLines(cands) {
    if (!cands.length) return ["물어볼 수 있는 조력자가 없어요.", "⑤ 조력자에서 조력자를 정할 수 있어요."];
    const names = namesText(cands.map((c) => c.name));
    return [`${names}: 돈을 받는 사람이에요.`, "그래서 이번에는 물어볼 수 없어요."];
  }

  function openAskStep(r) {
    const cands = askCandidates(r);
    const box = $("#card-ask");
    const back = h("button", { type: "button", class: "btn", onclick: closeAskStep },
      icon("question"), h("span", { text: "돌아가기" }));
    // 고를 사람이 없으면 요청을 보내지 않는다. 까닭을 보여 주고 다른 두 선택지로 돌아가게 한다.
    if (!cands.some((c) => !c.conflict)) {
      const lines = [...askNobodyLines(cands), "다른 것을 골라 주세요."];
      const orgs = (r.ask_helper_preview && r.ask_helper_preview.counseling_orgs) || [];
      fillWith(box,
        h("p", { class: "question", id: "card-ask-title", tabindex: "-1", text: "물어볼 조력자가 없어요" }),
        lines.map((t) => h("p", { text: t })),
        orgs.length ? h("div", { class: "notice" }, icon("person"), h("div", null,
          h("p", { text: COUNSELING_TITLE }), h("ul", null, orgs.map((o) => h("li", { text: o }))))) : null,
        speakButton(() => ["물어볼 조력자가 없어요.", ...lines, ...(orgs.length ? [COUNSELING_TITLE, ...orgs] : [])].join(" ")),
        h("div", { class: "choices" }, back));
      $("#card-choices").hidden = true;
      box.hidden = false;
      $("#card-ask-title").focus();
      return;
    }
    // 자동 알림 대상(⑤에서 정한 등급·범위): 체크를 풀 수 없게 두고 까닭을 적는다
    const auto = cands.filter((c) => c.auto && !c.conflict);
    const why = r.card && r.card.level === "high" ? "꼭 확인할 일이라" : "확인할 일이라";
    const label = (c) => {
      if (c.conflict) return `${c.name} (돈을 받는 사람이라 이번에는 물어볼 수 없어요)`;
      const who = c.relation ? `${c.name} (${c.relation})` : c.name;
      if (c.auto) return `${who} · ${why} ⑤에서 정한 대로 알려요`;
      return c.active === false ? `${who} · 자동으로 알리기는 꺼 두었어요` : who;
    };
    const list = h("div", { class: "ask-list" }, cands.map((c) => h("label", { class: "check-row" },
      h("input", {
        type: "checkbox", value: c.id, checked: !c.conflict && (c.default || c.auto),
        disabled: c.conflict || c.auto,
      }),
      icon("helper"),
      h("span", { text: label(c) }))));
    const err = h("p", { class: "error", role: "alert", hidden: true });
    const hints = ["체크한 사람에게 물어봐요. 문자나 메일은 보내지 않아요."];
    if (auto.length) {
      hints.push(`${namesText(auto.map((c) => c.name))}에게는 ⑤에서 정한 대로 알려요. 그래서 체크를 풀 수 없어요.`);
    }
    const spoken = () => ["누구에게 물어볼까요?", ...hints, ...cands.map((c) => `${label(c)}.`)].join(" ");
    fillWith(box,
      h("p", { class: "question", id: "card-ask-title", tabindex: "-1", text: "누구에게 물어볼까요?" }),
      hints.map((t) => h("p", { class: "small", text: t })),
      list, err,
      speakButton(spoken),
      h("div", { class: "choices" },
        h("button", {
          type: "button", class: "btn primary",
          onclick: () => {
            // 체크를 풀 수 없는 자동 알림 대상도 함께 보낸다(그 사람도 물어보는 알림을 받음)
            const ids = $$('input[type="checkbox"]', list).filter((b) => b.checked).map((b) => b.value);
            if (!ids.length) { err.textContent = "물어볼 사람을 한 명 이상 골라 주세요."; err.hidden = false; return; }
            chooseDecision("ask_helper", ids);
          },
        }, icon("helper"), h("span", { text: "체크한 사람에게 물어볼래요" })),
        back));
    $("#card-choices").hidden = true;
    box.hidden = false;
    $("#card-ask-title").focus();
  }

  function closeAskStep() {
    $("#card-ask").hidden = true;
    $("#card-choices").hidden = false;
    const ask = $('#card-choices [data-decision="ask_helper"]');
    if (ask) ask.focus();
  }

  function cardSpeakText() {
    const r = state.lastCheck;
    if (!r || !r.card) return "";
    const level = (LEVEL[r.card.level] || LEVEL.caution).text;   // 화면의 등급 배지
    const choices = r.card.choices.map((c) => c.label).join(", ");
    // 누가 알게 되는지(조력자 안내)도 함께 읽는다(#card-helper-note와 같은 글, 문장 사이 띄어쓰기)
    const note = $("#card-helper-note");
    const helperText = note && !note.hidden ? (state.cardHelperText || "").trim() : "";
    return `${level}. ${r.card.speak_text} ${helperText ? `${helperText} ` : ""}고를 수 있어요. ${choices}.`;
  }

  function closeCard() {
    $("#card-modal").hidden = true;
    $("#card-close").hidden = true;
    setBackgroundInert(false);
    document.body.style.overflow = "";
    stopSpeaking();
  }

  function setBackgroundInert(on) {
    for (const sel of [".skip-link", "header.top", "nav.tabs-wrap", "main"]) {
      const el = $(sel);
      if (!el) continue;
      if (on) { el.setAttribute("inert", ""); el.setAttribute("aria-hidden", "true"); } else {
        el.removeAttribute("inert"); el.removeAttribute("aria-hidden");
      }
    }
  }

  function trapFocus(e) {
    const modal = $("#card-modal");
    if (modal.hidden) return;
    if (e.key === "Escape") {
      // 닫기 대신 "안 보낼래요"로 초점만 옮긴다(물어볼 사람 고르기 중이면 앞 화면으로). 고르기는 당사자가 직접 한다.
      e.preventDefault();
      if (!$("#card-ask").hidden) { closeAskStep(); return; }
      const cancel = $('#card-choices [data-decision="cancel"]');
      if (cancel) cancel.focus();
      return;
    }
    if (e.key !== "Tab") return;
    const items = $$("button:not([disabled]), input:not([disabled]), [tabindex='-1']#card-title, [tabindex='-1']#card-ask-title",
      $(".modal-box", modal))
      .filter((el) => el.offsetParent !== null || el === document.activeElement);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); } else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }

  async function chooseDecision(decision, helperIds) {
    const buttons = $$("#card-choices button, #card-ask button");
    buttons.forEach((b) => { b.disabled = true; });
    try {
      await decide(decision, helperIds);
      closeCard();
      $("#pay-result").focus();
    } catch (err) {
      if (isConsentError(err)) {
        // 그 사이 동의가 꺼졌으면(다른 탭·명령행) 보내기처럼 막지 않고 연습 결과를 보여 준다
        const pending = state.pending;
        closeCard();
        if (pending) showUncheckedResult(pending);
        return;
      }
      const box = $("#card-error");
      const msg = /[.?!]$/.test(err.message) ? err.message : `${err.message}.`;
      box.textContent = `${msg} '닫기'를 누르고 다시 해 볼 수 있어요.`;
      box.hidden = false;
      const close = $("#card-close");
      close.hidden = false;       // 오류가 나도 모달에 갇히지 않게 닫기 버튼을 보여 준다
      close.focus();
    } finally {
      buttons.forEach((b) => { b.disabled = false; });
    }
  }

  function closeCardAfterError() {
    closeCard();
    $("#btn-pay").focus();
  }

  async function decide(decision, helperIds) {
    const body = { pending: state.pending, decision };
    if (decision === "ask_helper" && Array.isArray(helperIds)) body.helper_ids = helperIds;
    const r = await api("POST", "/api/safepause/decide", body);
    if (state.pending && r.pending) state.pending.id = r.pending.id;   // 서버가 새 id를 줬으면 그 id로 다시 시도
    showPayResult(r);
    state.payeesLoaded = false;
    refreshStatusLine();
    return r;
  }

  function showPayResult(r) {
    const t = r.pending;
    const plan = r.notify_plan || {};
    const icons = { send: "check", cancel: "stop", ask_helper: "helper" };
    // 제목·문장은 서버가 거래 방법에 맞게 만든다(이체: 보냈어요, 결제: 결제했어요 …)
    const title = r.result_title || r.message;
    const lines = [...(r.result_lines || [])];
    lines.push(`연습 시각: ${formatWhen(t.ts)}`);
    const tsNote = r.ts_note || (state.lastCheck && state.lastCheck.ts_note) || "";
    if (tsNote) lines.push(tsNote);
    const showCounseling = Boolean(plan.suggest_counseling && (plan.counseling_orgs || []).length);
    // 상담 안내 상자와 같은 문장이면 한 번만 보여 준다
    if (plan.note_to_person && !(showCounseling && plan.note_to_person === COUNSELING_TITLE)) {
      lines.push(plan.note_to_person);
    }

    const box = $("#pay-result");
    box.className = r.decision === "send" && r.assessment.level !== "none" ? "result" : "result ok";
    const children = [
      h("p", { class: "result-title" }, icon(icons[r.decision] || "check", "icon-lg"),
        h("span", { text: title })),
      lines.map((line) => h("p", { text: line })),
    ];
    const spokenParts = [title, ...lines];
    if (r.notices_recorded > 0) {
      const recorded = `${r.delivery_note} (기록 ${r.notices_recorded}건)`;
      children.push(h("p", { class: "small", text: recorded }));
      spokenParts.push(recorded);
    }
    if (showCounseling) {
      children.push(h("div", { class: "notice" }, icon("person"), h("div", null,
        h("p", { text: COUNSELING_TITLE }),
        h("ul", null, plan.counseling_orgs.map((o) => h("li", { text: o }))))));
      spokenParts.push(COUNSELING_TITLE, `${plan.counseling_orgs.join(", ")}.`);
    }
    children.push(h("p", null, h("strong", { text: r.practice_note })));
    spokenParts.push(r.practice_note);
    const spoken = spokenParts.map((t) => (/[.?!]$/.test(t) ? t : `${t}.`)).join(" ");   // 제목 뒤에도 쉼
    children.push(speakButton(spoken));
    box.replaceChildren(...children.flat());
    box.hidden = false;
    if ($("#card-modal").hidden) box.focus();
    announce(title);
  }

  // ---- ④ 알림 카드 ----------------------------------------------------------
  let cardSeq = 0;
  function cardView(item) {
    const c = item.card;
    const t = item.txn;
    const lv = LEVEL[c.level] || LEVEL.caution;
    const id = `alert-card-${++cardSeq}`;
    return h("article", { class: `alert-card level-${c.level}`, "aria-labelledby": id },
      h("p", { class: `level-badge level-${c.level}` }, icon(lv.icon), h("span", { text: lv.text })),
      h("div", { class: "pictos", "aria-hidden": "true" }, c.pictograms.map((p) => icon(p))),
      h("h3", { id, text: c.title }),
      h("p", { class: "small", text: `${formatWhen(t.ts)} · ${t.counterparty || "(이름 없음)"} · ${formatWon(t.amount)}` }),
      h("ul", { class: "card-lines" }, c.lines.map((line) => h("li", { text: line }))),
      h("p", { class: "question", text: c.question }),
      speakButton(c.speak_text));
  }

  async function loadCards() {
    const status = $("#cards-status");
    const list = $("#cards-list");
    setStatus(status, "불러오는 중이에요…");
    try {
      const d = await api("GET", "/api/cards?limit=30");
      list.replaceChildren(...d.items.map(cardView));
      setStatus(status, d.total
        ? `걱정했던 거래 ${nf.format(d.total)}건 가운데 최근 ${d.items.length}건이에요.`
        : "걱정했던 거래가 없어요.");
    } catch (e) {
      list.replaceChildren();
      showError(status, e);
    }
    loadDecisions();
  }

  async function loadDecisions() {
    const list = $("#decisions-list");
    try {
      const d = await api("GET", "/api/decisions");
      setStatus($("#decisions-status"), d.items.length ? "" : "아직 고른 것이 없어요.");
      const decisionText = (x) => (x.decision === "ask_helper" && x.asked === 0
        ? ASK_NOBODY_KO : (DECISION_KO[x.decision] || x.decision));
      list.replaceChildren(...d.items.slice(0, 50).map((x) => h("li", null,
        icon(DECISION_ICON[x.decision] || "check"), " ",
        h("strong", { text: decisionText(x) }),
        ` · ${(LEVEL[x.level] || LEVEL.none).text} · ${formatWhen(x.at)}`)));
    } catch (e) {
      list.replaceChildren();
      showError($("#decisions-status"), e);
    }
  }

  // ---- ⑤ 조력자 ------------------------------------------------------------
  let helperSeq = 0;

  function labeled(id, text, control, hint) {
    return h("div", null, h("label", { for: id, text }), control, hint || null);
  }

  function helperForm(hp) {
    const n = ++helperSeq;
    const pre = `hp${n}`;
    const isNew = !hp.id;
    const scope = new Set(hp.signal_scope || []);
    const allSignals = scope.size === 0;

    const noCheck = { spellcheck: "false", autocapitalize: "off", autocorrect: "off" };   // 온라인 맞춤법 검사 끄기(S35)
    const nameInput = h("input", { id: `${pre}-name`, type: "text", maxlength: 30, autocomplete: "off", "data-f": "name", value: hp.name || "", ...noCheck });
    const idsInput = h("textarea", { id: `${pre}-ids`, rows: 2, maxlength: 600, "data-f": "identifiers", "aria-describedby": `${pre}-ids-hint`, text: (hp.identifiers || []).join(", "), ...noCheck });
    const legend = h("legend", { text: hp.name ? `조력자: ${hp.name}` : "새 조력자" });

    // 새 조력자는 이름을 계좌번호·이름 칸에도 채워 둔다(보이고 고칠 수 있음)
    idsInput.addEventListener("input", () => { idsInput.dataset.touched = "1"; });
    nameInput.addEventListener("input", () => {
      legend.textContent = nameInput.value.trim() ? `조력자: ${nameInput.value.trim()}` : "새 조력자";
      if (isNew && idsInput.dataset.touched !== "1") idsInput.value = nameInput.value.trim();
    });

    const allBox = h("input", { type: "checkbox", "data-f": "scope-all", checked: allSignals });
    const signalBoxes = SIGNALS.map((code) => h("input", {
      type: "checkbox", "data-f": "scope", value: code, checked: scope.has(code), disabled: allSignals,
    }));
    allBox.addEventListener("change", () => {
      signalBoxes.forEach((b) => { b.disabled = allBox.checked; if (allBox.checked) b.checked = false; });
    });

    const fs = h("fieldset", { class: "helper-form box", "data-id": hp.id || "" },
      legend,
      h("div", { class: "helper-grid" },
        labeled(`${pre}-name`, "이름", nameInput),
        labeled(`${pre}-rel`, "관계", h("input", { id: `${pre}-rel`, type: "text", maxlength: 40, list: "relation-options", "data-f": "relation", value: hp.relation || "", ...noCheck })),
        labeled(`${pre}-contact`, "연락처 (가려서 저장해요)", h("input", { id: `${pre}-contact`, type: "text", maxlength: 60, autocomplete: "off", "data-f": "contact", "aria-describedby": `${pre}-contact-hint`, value: hp.contact || "", ...noCheck }),
          h("p", { id: `${pre}-contact-hint`, class: "hint", text: "전화번호는 가운데를, 메일은 앞 두 글자 뒤를 가려서 저장해요. 연락처로 보내는 것은 없어요." }))),
      labeled(`${pre}-ids`, "이 사람의 계좌번호·이름 (쉼표나 줄바꿈으로 나눠요)", idsInput,
        h("p", { id: `${pre}-ids-hint`, class: "hint", text: "받는 사람이 여기 적은 계좌번호나 이름과 같으면, 이번에는 이 조력자에게 알리지 않아요." })),
      h("fieldset", { class: "choice-group" },
        h("legend", { text: "언제 알릴까요?" }),
        h("label", { class: "radio-card" }, h("input", { type: "radio", name: `${pre}-level`, value: "high", checked: hp.min_level !== "caution" }), h("span", { text: "꼭 확인할 때만 (처음 설정)" })),
        h("label", { class: "radio-card" }, h("input", { type: "radio", name: `${pre}-level`, value: "caution", checked: hp.min_level === "caution" }), h("span", { text: "확인할 때도" }))),
      h("fieldset", { class: "choice-group" },
        h("legend", { text: "무엇을 알릴까요?" }),
        h("label", { class: "check-row" }, allBox, h("span", { text: "모든 것" })),
        SIGNALS.map((code, i) => h("label", { class: "check-row" }, signalBoxes[i], icon(SIGNAL_ICON[code]), h("span", { text: SIGNAL_KO[code] })))),
      h("label", { class: "check-row" }, h("input", { type: "checkbox", "data-f": "active", checked: hp.active !== false, "aria-describedby": `${pre}-active-hint` }), h("span", { text: "이 조력자에게 자동으로 알리기" })),
      h("p", { id: `${pre}-active-hint`, class: "hint", text: "끄면 자동으로는 알리지 않아요. 카드에서 '조력자에게 물어볼래요'로 고를 때만 알려요." }),
      h("div", { class: "row" }, h("button", {
        type: "button", class: "btn danger",
        onclick: () => {
          fs.remove();
          setStatus($("#helpers-status"), "조력자를 뺐어요. '저장하기'를 눌러야 바뀌어요.");
          $("#btn-add-helper").focus();
        },
      }, h("span", { text: "이 조력자 빼기" }))));
    return fs;
  }

  function renderHelpers(helpers) {
    const list = $("#helpers-list");
    list.replaceChildren(...helpers.map(helperForm));
    if (!helpers.length) list.append(h("p", { class: "small", text: "아직 조력자가 없어요. '조력자 더하기'를 눌러 주세요." }));
  }

  async function loadHelpers() {
    try {
      const [helpers, consent] = await Promise.all([api("GET", "/api/helpers"), api("GET", "/api/consent")]);
      renderHelpers(helpers);
      $("#helpers-consent-note").textContent = consent.helper_alerts
        ? "조력자에게 알리기: 켜짐."
        : "조력자에게 알리기가 꺼져 있어요. 자동으로 알리려면 ① 동의에서 켜 주세요. "
          + "(카드에서 '조력자에게 물어볼래요'를 직접 고르면 그때는 알려요.)";
    } catch (e) {
      showError($("#helpers-status"), e);
    }
    loadNotices();
  }

  function collectHelpers() {
    const helpers = [];
    for (const [i, fs] of $$("#helpers-list > fieldset.helper-form").entries()) {
      const get = (f) => $(`[data-f="${f}"]`, fs);
      const name = get("name").value.trim();
      if (!name) return { error: `${i + 1}번째 조력자의 이름을 적어 주세요.`, focus: get("name") };
      const all = get("scope-all").checked;
      const scope = all ? [] : $$('[data-f="scope"]:checked', fs).map((b) => b.value);
      if (!all && !scope.length) return { error: `${name}: 알릴 것을 하나 이상 골라 주세요.`, focus: get("scope-all") };
      const level = $('input[type="radio"]:checked', fs);
      helpers.push({
        id: fs.dataset.id || null,
        name,
        relation: get("relation").value.trim(),
        contact: get("contact").value.trim(),
        identifiers: get("identifiers").value.split(/[,\n]/).map((s) => s.trim()).filter(Boolean),
        min_level: level ? level.value : "high",
        signal_scope: scope,
        active: get("active").checked,
      });
    }
    return { helpers };
  }

  async function saveHelpers() {
    const status = $("#helpers-status");
    const { helpers, error, focus } = collectHelpers();
    if (error) { setStatus(status, error, "error"); if (focus) focus.focus(); return; }
    const btn = $("#btn-save-helpers");
    btn.disabled = true;
    try {
      const saved = await api("PUT", "/api/helpers", helpers);
      renderHelpers(saved);
      setStatus(status, `저장했어요. 조력자 ${saved.length}명.`, "ok");
      announce("조력자를 저장했어요.");
      refreshStatusLine();
    } catch (e) {
      showError(status, e);
    } finally {
      btn.disabled = false;
    }
  }

  function addHelper() {
    const list = $("#helpers-list");
    $("p.small", list)?.remove();
    const fs = helperForm({ name: "", relation: "", contact: "", identifiers: [], min_level: "high", signal_scope: [], active: true });
    list.append(fs);
    $('[data-f="name"]', fs).focus();
  }

  async function loadNotices() {
    const list = $("#notices-list");
    try {
      const d = await api("GET", "/api/notices");
      $("#delivery-note").textContent = d.delivery_note;
      list.replaceChildren(...d.items.slice(0, 50).map((n) => h("li", null,
        h("strong", { text: n.helper_name }),
        ` · ${(LEVEL[n.level] || LEVEL.none).text} · ${formatWhen(n.created_at)}`,
        h("p", { class: "small", text: n.message }))));
      if (!d.items.length) list.append(h("li", { text: "아직 알림 기록이 없어요." }));
    } catch (e) {
      list.replaceChildren(h("li", { text: e.message }));
    }
  }

  // ---- ⑥ 성능 확인 ----------------------------------------------------------
  function table(caption, head, rows) {
    return h("div", { class: "table-scroll" }, h("table", null,
      h("caption", { text: caption }),
      h("thead", null, h("tr", null, head.map((x) => h("th", { scope: "col", text: x })))),
      h("tbody", null, rows.map((r) => h("tr", null,
        h("th", { scope: "row", text: r[0] }),
        r.slice(1).map((v) => h("td", { class: "num", text: v })))))));
  }

  function renderEval(r) {
    const modes = r.modes.filter((m) => r.results[m]);
    const res = modes.map((m) => r.results[m]);
    const first = res[0] || {};
    const head = ["지표", ...modes.map((m) => `${MODE_KO[m] || m} (${m})`)];
    const pick = (fn) => res.map((x) => { try { return fn(x); } catch (e) { return "-"; } });
    const summary = [
      ["시나리오 찾음 (주의 이상)", ...pick((x) => `${percent(x.overall.recall_caution)} (${x.overall.caution}/${x.overall.n})`)],
      ["시나리오 찾음 (고위험)", ...pick((x) => `${percent(x.overall.recall_high)} (${x.overall.high}/${x.overall.n})`)],
      ["평소 거래를 잘못 알림 (주의 이상 비율)", ...pick((x) => percent(x.normal.alert_rate))],
      ["평소 거래가 고위험이 됨 (조력자 알림 대상)", ...pick((x) => percent(x.normal.high_rate))],
      ["평소 거래 알림 한 달 평균 (건)", ...pick((x) => num(x.normal.monthly_alerts))],
      ["걱정 거래 없는 대조군: 한 달 평균 알림 (건)", ...pick((x) => (x.control ? num(x.control.monthly_alerts) : "-"))],
      ["걱정 거래 없는 대조군: 한 달 평균 고위험 (건)", ...pick((x) => (x.control ? num(x.control.monthly_high) : "-"))],
    ];
    const codes = Object.keys(first.scenario_recall || {});
    const perScenario = codes.map((code) => [SIGNAL_KO[code] || code,
      ...pick((x) => { const s = x.scenario_recall[code]; return `${percent(s.recall_caution)} / ${percent(s.recall_high)}`; })]);

    const meta = `인물 ${r.personas.length}명 × seed ${r.seeds.length}개 = 사례 ${first.n_cases ?? "-"}개. `
      + `앞 ${first.baseline_days ?? "-"}일로 배우고 뒤 ${first.eval_days ?? "-"}일을 확인했어요.`;
    $("#eval-result").replaceChildren(
      h("p", { text: meta }),
      table("요약", head, summary),
      codes.length ? table("걱정 거래 종류별 찾음 (주의 이상 / 고위험)", ["종류", ...head.slice(1)], perScenario) : null,
      h("p", { class: "small", text: `모델: ${[...new Set(res.flatMap((x) => x.model_versions || []))].join(", ") || "-"}` }),
      h("p", null, h("strong", { text: r.note })));
  }

  async function runEval() {
    const status = $("#eval-status");
    const modes = $$('input[name="eval-mode"]:checked').map((b) => b.value);
    if (!modes.length) { setStatus(status, "방식을 하나 이상 골라 주세요.", "error"); return; }
    const seeds = parseInt($("#eval-seeds").value, 10) || 3;
    const btn = $("#btn-eval");
    btn.disabled = true;
    $("#eval-result").setAttribute("aria-busy", "true");
    setStatus(status, "계산하고 있어요. 몇 초에서 1분쯤 걸려요…");
    try {
      const r = await api("POST", "/api/eval/run", { seeds, modes });
      renderEval(r);
      setStatus(status, `다 했어요 (${r.elapsed_sec}초).`, "ok");
      announce("성능 확인을 마쳤어요.");
    } catch (e) {
      showError(status, e);
    } finally {
      btn.disabled = false;
      $("#eval-result").removeAttribute("aria-busy");
    }
  }

  async function runEvalFile() {
    const status = $("#eval-mine-status");
    const out = $("#eval-mine-result");
    const btn = $("#btn-eval-mine");
    btn.disabled = true;
    setStatus(status, "계산하고 있어요…");
    try {
      const r = await api("POST", "/api/eval/file");
      const bySignal = Object.entries(r.by_signal || {}).map(([code, n]) => `${SIGNAL_KO[code] || code} ${n}건`).join(", ");
      const rows = [
        ["저장된 거래", `${nf.format(r.n_total)}건`],
        ["AI가 평소 모습을 배운 구간 (앞쪽)", learnedRows(r.n_baseline, r.n_train_rows)],
        ["확인한 거래 (뒤쪽)", `${nf.format(r.n_eval)}건 · ${r.eval_days}일`],
        ["알림 (주의 이상)", `${r.alerts}건 (${percent(r.alert_rate)})`],
        ["고위험 (조력자 알림 대상)", `${r.high}건 (${percent(r.high_rate)})`],
        ["한 달 평균 알림", `${num(r.monthly_alerts)}건`],
        ["알림 이유 (규칙)", bySignal || "없음"],
        ["AI만 알린 것", `${r.anomaly_only}건`],
      ];
      out.replaceChildren(
        table("내 거래로 확인한 결과", ["항목", "값"], rows),
        r.labeled_note ? h("p", { class: "notice-strong", text: r.labeled_note }) : null,
        h("p", null, h("strong", { text: r.note })));
      setStatus(status, "다 했어요.", "ok");
    } catch (e) {
      out.replaceChildren();
      showError(status, e);
    } finally {
      btn.disabled = false;
    }
  }

  // ---- ⑦ 지우기 ------------------------------------------------------------
  function askWipe() {
    $("#wipe-confirm").hidden = false;
    $("#btn-wipe-no").focus();   // 안전한 쪽에 먼저 초점
  }

  function clearShownData() {
    // 화면과 메모리에 남은 거래 내용(받는 사람·금액·카드 문장)을 모두 지운다
    if (!$("#card-modal").hidden) closeCard();
    state.payeesLoaded = false;
    state.txnItems = [];
    state.txnShown = 0;
    state.pending = null;
    state.lastCheck = null;
    state.cardHelperText = "";
    for (const sel of ["#txn-list", "#payee-list", "#cards-list", "#notices-list", "#decisions-list",
      "#card-lines", "#card-choices", "#card-ask", "#eval-mine-result", "#card-title", "#card-question",
      "#card-pictos", "#card-helper-note", "#card-error", "#helpers-list", "#pay-amount-easy"]) {
      const el = $(sel);
      if (el) el.replaceChildren();
    }
    $("#card-helper-note").hidden = true;
    for (const sel of ["#pay-result", "#upload-report", "#data-summary", "#txn-status", "#cards-status",
      "#decisions-status", "#eval-mine-status", "#data-status"]) {
      const el = $(sel);
      if (!el) continue;
      el.replaceChildren();
      if (sel === "#pay-result") el.hidden = true;
    }
    $("#btn-more").hidden = true;
    // 보내기 연습 입력칸(받는 사람·금액·계좌번호)과 올리기 칸(파일·열 이름 지정)도 비운다
    $("#pay-form").reset();
    $("#pay-error").hidden = true;
    const file = $("#upload-file");
    if (file) file.value = "";
    const mapping = $("#upload-mapping");
    if (mapping) mapping.value = "";
  }

  async function doWipe() {
    const status = $("#wipe-status");
    try {
      const r = await api("POST", "/api/wipe");
      $("#wipe-confirm").hidden = true;
      clearShownData();
      setStatus(status, r.message, "ok");
      announce(r.message);
      refreshStatusLine();
      $("#btn-wipe").focus();
    } catch (e) {
      clearShownData();   // 일부만 지워졌어도 화면에는 남기지 않는다
      showError(status, e);
      refreshStatusLine();
    }
  }

  // ---- 시작 ----------------------------------------------------------------
  function init() {
    fillIcons();
    $$(".switch[data-consent]").forEach((btn) => btn.addEventListener("click", () => toggleConsent(btn)));
    $$('input[name="given_by"]').forEach((r) => r.addEventListener("change", () => changeGivenBy(r.value)));

    $("#btn-sample").addEventListener("click", loadSample);
    $("#btn-upload").addEventListener("click", uploadFile);
    $("#btn-more").addEventListener("click", showMoreTxns);
    $$(".filter").forEach((b) => b.addEventListener("click", () => {
      state.txnFilter = b.dataset.filter;
      $$(".filter").forEach((x) => x.setAttribute("aria-pressed", x === b ? "true" : "false"));
      loadTxns();
    }));

    $("#pay-form").addEventListener("submit", onPay);
    $("#pay-amount").addEventListener("input", updateAmountEasy);
    $$("[data-example]").forEach((b) => b.addEventListener("click", () => fillExample(b.dataset.example)));
    $("#card-speak").addEventListener("click", () => speak(cardSpeakText()));
    $("#card-close").addEventListener("click", closeCardAfterError);
    document.addEventListener("keydown", trapFocus);

    $("#btn-add-helper").addEventListener("click", addHelper);
    $("#btn-save-helpers").addEventListener("click", saveHelpers);

    $("#btn-eval").addEventListener("click", runEval);
    $("#btn-eval-mine").addEventListener("click", runEvalFile);

    $("#btn-wipe").addEventListener("click", askWipe);
    $("#btn-wipe-yes").addEventListener("click", doWipe);
    $("#btn-wipe-no").addEventListener("click", () => { $("#wipe-confirm").hidden = true; $("#btn-wipe").focus(); });

    initTabs();
    refreshStatusLine();
  }

  init();
})();
