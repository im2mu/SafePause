/* 알림 보내기(보내기 탭의 둘째 탭, #/send?mode=notify): 무엇을 → 누구에게 → 어떻게(받는 사람 무리마다 방법·글·앱 열기).
 * - SafePause가 직접 보내지 않는다. 글을 채운 문자·메일 앱(전화는 다이얼 화면)을 열고, 보내기는 사람이 누른다.
 * - 앱을 열면 보낸 알림 기록을 남긴다(POST /api/notices/record, 번호·메일 원본은 서버가 넣지 않음) → 알림 탭 보낸 알림.
 * - 조력자와 상담하는 곳은 한 문자·메일에 묶지 않는다(받는 사람끼리 번호가 드러나지 않게, RF-5): 무리마다 따로 앱을 연다.
 *   상담하는 곳은 번호가 있으면 전화(다이얼 화면)가 기본이고, 글에는 보내는 사람과 요청을 넣는다(J12, 내 이름은 선택).
 * - 주소 뒤 값
 *   txn=<거래 id>(여러 번 또는 쉼표로 이어서)이면 그 거래를 미리 고른다. 고른 거래가 바뀌면 주소도 바꾼다(새로 고쳐도 남게, RF-8).
 *   to=counselors면 상담하는 곳을 펼치고 추천받은 상담하는 곳만 미리 체크한다. 그 밖에는 상담하는 곳을 저절로 체크하지 않는다.
 *   helper=<조력자 id>(돈 보내기에서 물어볼 사람으로 고른 사람)는 그 사람만 미리 체크한다.
 *   ask=1(돈 보내기의 물어볼래요)이면 묻는 글로 채우고, channel=sms|email이면 그 방법을 먼저 고른다.
 *   resend=<보낸 알림 id>면 그 알림의 받는 사람·글·거래로 채운다(다시 보내기, AUG-06).
 * - 받는 사람 추천: 거래를 고르거나 바꿀 때 POST /api/notify/suggest로 조력자 설정(알릴 등급·범위·자동으로 알리기)에 맞는
 *   사람을 미리 체크하고 추천 배지를 단다. 저장하지 않은 확인 거래(돈 보내기의 안 보낼래요·물어볼래요)는 pending으로 함께 넘긴다(RF-1).
 *   그 거래에서 돈을 받은 조력자는 체크를 풀고 경고한다. 그래도 체크하면 보내기 전에 한 번 더 묻는다(본인 결정).
 *   추천을 못 받으면(옛 엔진·동의 꺼짐·오류) 추천 없이 쓰되, 돈 보내기가 알려 준 돈 받는 조력자는 그대로 경고한다.
 * - 받는 사람은 한 번에 10명까지다. 10명을 고르면 나머지 체크 칸을 끄고 안내한다(말없이 자르지 않음, FN-06).
 * - 보내기 탭(send.js)이 이 화면의 ctx를 따로 만들어 넘긴다(ctx.main = 탭 칸).
 * - 화면이 쓰는 도우미는 모두 function 선언이다(받는 사람 목록보다 추천이 먼저 와도 그릴 수 있게, RF-2·L1).
 */
import { h, icon, fill, setText, splitSentences, openSheet, confirmSheet, toast, announce, skeleton } from "../ui.js";
import { txnSignals, txnAmount, levelBadge, flagBadge, reviewBadge, notifiedBadge, checkedBadge, errorNotice, subParts, speakButton } from "../components.js";
import { moneyText, formatTime, parseTs, nf, deviceWord, breakableEmail } from "../format.js";
import { CHANNEL_KO, CHANNEL_ICON, COUNSELOR_KIND_KO, COUNSELOR_KIND_ICON } from "../labels.js";
import { capabilities, openExternal, smsUri, mailtoUri, telUri, copyText } from "../native.js";
import { STALE } from "../api.js";
import { checkedItem } from "./money.js";

const MAX_PICK = 5;          // 한 번에 알릴 거래(문자 한 통에 읽기 좋은 만큼)
const MAX_MESSAGE = 1000;    // api MAX_NOTICE_MESSAGE
const MAX_TO = 10;           // api MAX_NOTICE_RECIPIENTS
const PAGE = 50;             // 거래 고르기에서 한 번에 불러오는 거래 수
const MAX_NAME = 20;
const NO_CHECK = { spellcheck: "false", autocorrect: "off", autocapitalize: "off" };
export const MY_NAME_KEY = "safepause.myName";
const CHANNELS = {
  sms: { value: "sms", label: "문자", icon: "chat", app: "문자 앱" },
  email: { value: "email", label: "메일", icon: "mail", app: "메일 앱" },
  call: { value: "call", label: "전화", icon: "call", app: "전화 걸기 화면" },
};
// 받는 사람 무리: 조력자(문자·메일), 상담하는 곳(전화·문자·메일). to는 받는 사람 뒤 조사
const GROUPS = {
  helper: { kind: "helper", ways: ["sms", "email"], title: "조력자", unit: "명", to: "에게", icon: "users" },
  counselor: { kind: "counselor", ways: ["call", "sms", "email"], title: "상담하는 곳", unit: "곳", to: "에", icon: "building" },
};
const SUBJECT = "[SafePause] 걱정되는 거래 알림";
const SUBJECT_ASK = "[SafePause] 보내기 전에 물어봐요";
const SUBJECT_DIRECT = "[SafePause] 도움 요청";
const SUBJECT_COUNSEL = "[SafePause] 상담 요청";
const DIRECT_TEXT = "[SafePause] 돈 문제로 도움이 필요해서 알려요.\n";
const CONFLICT_WARN = "이 거래에서 돈을 받은 사람이에요. 다른 사람에게 알리는 게 좋아요.";
const PICK_TABS = [
  { value: "high", label: "꼭 확인할 거래", path: "/api/transactions?level=high" },
  { value: "caution", label: "걱정되는 거래", path: "/api/transactions?level=caution" },
  { value: "flags", label: "담은 거래", path: "/api/flags" },
];

/** 상담하는 곳에 보내는 글에 넣을 내 이름(선택, 이 휴대폰·이 컴퓨터에만 기억). */
export function getMyName() {
  try { return String(localStorage.getItem(MY_NAME_KEY) || "").slice(0, MAX_NAME); } catch (e) { return ""; }
}
function saveMyName(name) {
  try { if (name) localStorage.setItem(MY_NAME_KEY, name); else localStorage.removeItem(MY_NAME_KEY); } catch (e) { /* 저장 못 해도 이번 글에는 쓴다 */ }
}
/** 기억한 내 이름을 지운다(모두 지우기 때 부른다). */
export function clearMyName() {
  try { localStorage.removeItem(MY_NAME_KEY); } catch (e) { /* 무시 */ }
}

/** "6월 27일 새벽 4시 41분" */
function whenText(ts) {
  const d = parseTs(ts);
  return d ? `${d.getMonth() + 1}월 ${d.getDate()}일 ${formatTime(d)}` : "";
}

/** 거래 한 건을 글 한 줄로: 때, 상대, 방법 금액. 표시 이름. */
function txnLine(item) {
  const t = item.txn;
  const head = [whenText(t.ts), t.counterparty || "이름 없음", `${CHANNEL_KO[t.channel] || "거래"} ${moneyText(t.amount)}`].filter(Boolean).join(", ");
  const why = txnSignals(item).map((s) => s.text);
  return why.length ? `${head}. ${why.join(", ")}.` : `${head}.`;
}
function txnLines(picked) {
  return picked.length === 1 ? [txnLine(picked[0])] : picked.map((it, i) => `${i + 1}) ${txnLine(it)}`);
}

/** 조력자에게 보낼 글. ask면 돈을 보내기 전에 묻는 글. */
function helperText(picked, ask) {
  if (!picked.length) return DIRECT_TEXT;
  if (ask) return ["[SafePause] 돈을 보내기 전에 물어보고 싶어요.", ...txnLines(picked), "보내도 될지 같이 봐 주세요."].join("\n");
  if (picked.length === 1) return `[SafePause] 걱정되는 거래가 있어 알려요.\n${txnLine(picked[0])}\n확인해 주세요.`;
  return [`[SafePause] 걱정되는 거래 ${picked.length}건이 있어 알려요.`, ...txnLines(picked), "확인해 주세요."].join("\n");
}

/** 상담하는 곳에 보낼 글(또는 전화로 말할 내용): 보내는 사람 + 요청 + 거래(J12). */
function counselText(picked, name, call) {
  const need = picked.length ? "걱정되는 거래가 있어 상담을 받고 싶어요." : "돈 문제로 상담을 받고 싶어요.";
  const who = name ? `${name}입니다.` : "";
  const lines = [call ? ["안녕하세요.", who ? `저는 ${who}` : "", need].filter(Boolean).join(" ")
    : `[SafePause] ${who ? `${who} ` : ""}${need}`];
  if (picked.length) lines.push("SafePause 앱이 걱정된다고 알려 준 거래예요.", ...txnLines(picked));
  if (!call) lines.push("답장이나 전화로 연락 주세요.");
  return lines.join("\n");
}

/** 404인데 쉬운 말 안내가 없으면(새 기능을 아직 못 쓰는 엔진) 쉬운 말로 바꾼다. */
function friendlyError(e) {
  if (e && e.status === 404 && !/[가-힣]/.test(String(e.message || ""))) {
    return Object.assign(new Error("이 목록을 아직 불러올 수 없어요. 잠시 뒤 다시 해 주세요."), { status: 404 });
  }
  return e;
}

/** 저장하지 않은 확인 거래를 추천 요청의 pending(PendingIn 모양)으로. */
function pendingOf(it) {
  const t = it.txn || {};
  const channel = ["transfer", "card", "micropay"].includes(t.channel) ? t.channel : "transfer";
  const p = {
    to: String(t.counterparty || "이름 없음").slice(0, 40), amount: Math.min(10000000000, Math.max(1, Math.round(Number(t.amount) || 0))),
    channel, to_id: String(t.counterparty_id || "").slice(0, 60),
  };
  if (t.id) p.id = String(t.id).slice(0, 40);
  if (t.ts) p.ts = t.ts;
  return p;
}

const isLive = (id) => /^live-/.test(String(id || ""));

export default {
  title: "알림 보내기",
  tab: "send",
  async render(ctx) {
    const { main, go } = ctx;
    const caps = capabilities();
    const params = ctx.params;
    const listParam = (name) => params.getAll(name).flatMap((v) => String(v).split(",")).map((s) => s.trim()).filter(Boolean);
    const wantIds = [...new Set(listParam("txn"))].slice(0, MAX_PICK);
    const toCounselors = params.get("to") === "counselors";
    const wantHelpers = new Set(listParam("helper"));
    const askMode = params.get("ask") === "1";
    const wantChannel = ["sms", "email"].includes(params.get("channel")) ? params.get("channel") : "";
    const resendId = String(params.get("resend") || "").slice(0, 40);

    // ---- 상태(그리기 함수보다 먼저 둔다) ----
    let picked = [];            // 고른 거래(_item 형식)
    let helpers = [];
    let counselors = [];
    const chosen = new Set();   // 고른 받는 사람 key("helper:h1", "counselor:c1")
    const touched = new Set();  // 본인이 직접 체크를 바꾼 받는 사람(추천이 덮어쓰지 않음)
    const rows = new Map();     // key → {box, row}
    const done = new Set();     // 앱을 연 받는 사람 무리(helper, counselor, call:<key>)
    let counselorsOpen = toCounselors;
    let monitoring = true;      // 거래 살펴보기 동의(꺼져 있으면 거래를 부르지 않고 직접 적기만)
    let suggestion = null;      // 받는 사람 추천 {helpers: Map, counselors: Map, due, reason}. 못 받으면 null
    let suggestSeq = 0;
    let myName = getMyName();
    let resendRec = null;       // 다시 보내기로 채울 보낸 알림 기록
    let resendPeopleDone = false;
    let helpersLoaded = false;  // 목록을 받기 전에는 빈 목록 안내 대신 자리표시를 둔다
    let counselorsLoaded = false;

    // ---- 1 무엇을 알릴까요 ----
    const pickedSlot = h("div", { class: "np-picked-slot" }, skeleton(1));
    const step1 = stepCard(1, "np-s1", "무엇을 알릴까요?",
      pickedSlot,
      h("div", { class: "btn-row np-step-btns" },
        h("button", { type: "button", class: "btn weak", onclick: openPicker }, icon("list"), h("span", { text: "거래 고르기" })),
        h("button", { type: "button", class: "btn", onclick: writeDirect }, icon("edit"), h("span", { text: "거래 없이 직접 적기" }))));

    // ---- 2 누구에게 알릴까요 ----
    const helperSlot = h("div", null, skeleton(1));
    const recLine = h("p", { class: "np-rec-line", hidden: true });
    const counselorSlot = h("div", { id: "np-counselors" });
    const counselRec = h("p", { class: "np-rec-line np-counsel-rec", hidden: true });
    const limitLine = h("p", { class: "np-limit", role: "status", hidden: true });
    const counselorToggle = h("button", { type: "button", class: "np-expand", "aria-controls": "np-counselors", "aria-expanded": "false", onclick: () => { counselorsOpen = !counselorsOpen; paintCounselorToggle(); } },
      h("span", { class: "np-expand-main" }, icon("building"), h("span", { class: "np-expand-text", text: "상담하는 곳" })),
      icon("chevron-down", "np-chev"));
    const step2 = stepCard(2, "np-s2", "누구에게 알릴까요?",
      recLine,
      h("div", { class: "np-group-title" }, h("span", { text: "조력자" })),
      helperSlot,
      h("div", { class: "np-divider", "aria-hidden": "true" }),
      counselorToggle, counselRec, counselorSlot, limitLine);

    // ---- 3 어떻게 보낼까요(무리마다 방법·글·앱 열기) ----
    const groups = { helper: makeGroup("helper"), counselor: makeGroup("counselor") };
    const groupList = [groups.helper, groups.counselor];
    const emptyLine = h("p", { class: "np-empty-line", text: "2번에서 받는 사람을 고르면 여기에서 보낼 수 있어요." });
    const step3 = stepCard(3, "np-s3", "어떻게 보낼까요?", emptyLine, groups.helper.el, groups.counselor.el,
      h("p", { class: "np-must", text: "보내기 버튼은 문자·메일 앱에서 직접 눌러요." }));

    fill(main,
      h("p", { class: "page-sub", text: "걱정되는 거래를 조력자와 상담하는 곳에 알려요." }),
      step1, step2, step3,
      h("a", { class: "btn ghost block np-sent-link", href: "#/alerts?tab=sent" }, icon("bell"), h("span", { text: "보낸 알림 보기" })));

    // 직접 고친 글이 있으면 떠나기 전에 묻는다(다시 보내기로 채운 지난 글은 보낸 알림에 남아 있으니 고치지 않았으면 묻지 않는다)
    const guard = () => confirmSheet({ title: "고친 글이 있어요", lines: ["나가면 고친 글이 사라져요."], confirmText: "나가기", cancelText: "계속 쓰기" });
    function setGuard() {
      const edited = groupList.some((g) => g.edited && g.msg.value !== g.base);
      ctx.session.unsaved = edited ? guard : (ctx.session.unsaved === guard ? null : ctx.session.unsaved);
    }
    ctx.onCleanup(() => { if (ctx.session.unsaved === guard) ctx.session.unsaved = null; });

    for (const g of groupList) setMsg(g, autoText(g));
    paintCounselorToggle();
    paint();

    // ---- 불러오기: 받는 사람(조력자·상담하는 곳)과 미리 고를 거래를 함께 ----
    const consentReady = ctx.req("GET", "/api/consent").then((c) => {
      ctx.session.consent = c;
      monitoring = Boolean(c && c.monitoring);
    }).catch(() => {});   // 못 읽으면 그대로 불러 보고, 오류는 그 자리에서 알린다
    const resendReady = resendId ? loadResend() : Promise.resolve(null);
    await Promise.all([loadPeople(), loadPreset()]);
    if (!ctx.alive()) return;
    if (resendRec) applyResendMessage(resendRec);

    // ================= 불러오기 =================
    async function loadResend() {
      try {
        const d = await ctx.req("GET", "/api/notices");
        const rec = (d.items || []).find((x) => x.kind === "manual" && String(x.id) === resendId) || null;
        if (!rec) toast("다시 보낼 알림을 찾지 못했어요.", "error");
        resendRec = rec;
        return rec;
      } catch (e) {
        if (e !== STALE) toast("다시 보낼 알림을 불러오지 못했어요.", "error");
        return null;
      }
    }

    async function loadPeople() {
      const [hp, co] = await Promise.allSettled([ctx.req("GET", "/api/helpers"), ctx.req("GET", "/api/counselors")]);
      if ([hp, co].some((r) => r.status === "rejected" && r.reason === STALE)) return;
      if (hp.status === "fulfilled") {
        const list = Array.isArray(hp.value) ? hp.value : (hp.value && hp.value.items) || [];
        helpers = list.map((x) => ({
          key: `helper:${x.id}`, kind: "helper", id: String(x.id), name: x.name, icon: "person",
          sub: [x.relation, x.phone_masked || (x.email_masked ? breakableEmail(x.email_masked) : "")].filter(Boolean).join(" · "),
          phone: x.phone || "", email: x.email || "",
        }));
        // 돈 보내기에서 물어볼 사람을 골라 왔으면 그 사람만 체크해 둔다(추천이 덮어쓰지 않게, 추천 배지는 보인다)
        if (wantHelpers.size) for (const p of helpers) { touched.add(p.key); if (wantHelpers.has(p.id) && !isConflict(p)) addChosen(p.key); }
        helpersLoaded = true;
      } else {
        fill(helperSlot, retryBox(hp.reason, loadPeople));
      }
      if (co.status === "fulfilled") {
        counselors = ((co.value && co.value.items) || []).filter((x) => x.active !== false).map((x) => ({
          key: `counselor:${x.id}`, kind: "counselor", id: String(x.id), name: x.name, icon: COUNSELOR_KIND_ICON[x.kind] || "building",
          // 이름에 종류가 이미 있으면(장애인권익옹호기관 …) 종류를 또 쓰지 않는다
          sub: [String(x.name).includes(COUNSELOR_KIND_KO[x.kind] || "") ? "" : COUNSELOR_KIND_KO[x.kind],
            x.phone || (x.email ? breakableEmail(x.email) : "")].filter(Boolean).join(" · "),
          phone: x.phone || "", email: x.email || "",
        }));
        if (!helpers.length) counselorsOpen = true;   // 조력자가 없으면 상담하는 곳을 펼쳐 둔다
        if (wantHelpers.size) for (const p of counselors) touched.add(p.key);
        counselorsLoaded = true;
      } else {
        counselorsOpen = true;
        fill(counselorSlot, retryBox(co.reason, loadPeople));
      }
      const rec = await resendReady;
      if (!ctx.alive()) return;
      if (rec && !resendPeopleDone) applyResendPeople(rec);
      applySuggestion(false);
      if (hp.status === "fulfilled") renderHelpers();
      if (co.status === "fulfilled") renderCounselors();
      paintCounselorToggle();
      paint();
    }

    async function loadPreset() {
      await consentReady;
      const rec = await resendReady;
      if (!ctx.alive()) return;
      if (!monitoring) { renderPicked(); paint(); return; }   // 동의가 꺼져 있으면 추천도 받지 않는다
      const ids = rec ? [...new Set((rec.txn_ids || []).map(String))].slice(0, MAX_PICK) : wantIds;
      try {
        if (ids.length) {
          picked = await findTxns(ids);
          const missing = ids.filter((id) => !picked.some((it) => it.txn.id === id));
          if (missing.length) {
            toast(missing.every(isLive) ? "보내기 전에 확인한 거래는 저장하지 않아요. 그래서 다시 고를 수 없어요."
              : "고른 거래 가운데 지금 없는 거래는 뺐어요.", "error");
          }
        } else if (toCounselors) {
          // 상담 안내에서 왔으면 최근 꼭 확인할 거래(내가 확인한 것 빼고)를 미리 골라 둔다(빼도 된다)
          const d = await ctx.req("GET", "/api/transactions?level=high&limit=10");
          picked = (d.items || []).filter((it) => !it.reviewed).slice(0, 3);
        }
      } catch (e) {
        if (e === STALE) return;
        picked = [];
        fill(pickedSlot, errorNotice(friendlyError(e), go));
        return;
      }
      refreshMessages();
      renderPicked();
      if (ids.length || toCounselors) syncUrl();   // 찾지 못한 거래는 주소에서도 뺀다
      paint();
      refreshSuggest();
    }

    /** 거래 id로 항목 찾기: 이 창에서 확인한 거래 → 걱정되는 거래 → 최근 거래부터 500건씩. */
    async function findTxns(ids) {
      const found = new Map();
      // 돈 보내기에서 방금 확인한 거래(안 보낼래요·물어볼래요는 거래 이력에 적지 않는다)는 이 창이 기억한 항목을 쓴다.
      // 모두 지우기·거래 살펴보기 끄기 뒤(세대가 바뀜)에는 쓰지 않는다(IA-1)
      for (const id of ids) { const c = checkedItem(id, ctx.session.epoch); if (c) found.set(id, c); }
      const want = new Set(ids.filter((id) => !found.has(id)));
      if (!want.size) return ids.map((id) => found.get(id)).filter(Boolean);
      const take = (items) => { for (const it of items || []) if (want.has(it.txn.id) && !found.has(it.txn.id)) found.set(it.txn.id, it); };
      take((await ctx.req("GET", "/api/transactions?level=caution&limit=200")).items);
      for (let offset = 0; [...want].some((id) => !found.has(id)) && offset < 20000; offset += 500) {
        const d = await ctx.req("GET", `/api/transactions?level=all&limit=500&offset=${offset}`);
        take(d.items);
        if (offset + 500 >= (d.matched ?? d.count ?? 0)) break;
      }
      return ids.map((id) => found.get(id)).filter(Boolean);
    }

    // ================= 다시 보내기 =================
    function applyResendPeople(rec) {
      resendPeopleDone = true;
      for (const p of [...helpers, ...counselors]) touched.add(p.key);
      let lost = 0;
      for (const r of rec.recipients || []) {
        const pool = r.kind === "counselor" ? counselors : helpers;
        // id는 목록을 새로 저장하면 다른 사람에게 다시 쓰일 수 있어 이름까지 같을 때만 믿는다
        const p = (r.id && pool.find((x) => x.id === String(r.id) && x.name === r.name)) || pool.find((x) => x.name === r.name);
        if (p && addChosen(p.key)) { if (p.kind === "counselor") counselorsOpen = true; } else lost += 1;
      }
      if (lost) toast("지난번 받는 사람 가운데 지금 목록에 없는 사람은 뺐어요.", "error");
    }
    function applyResendMessage(rec) {
      const message = String(rec.message || "").slice(0, MAX_MESSAGE);
      for (const g of groupList) {
        if (!people(g.kind).length) continue;
        if (rec.channel && g.def.ways.includes(rec.channel)) { g.channel = rec.channel; g.chosenWay = true; }
        if (message) { setMsg(g, message); g.edited = message !== autoText(g); g.base = message; }
      }
      setGuard();
      syncUrl();
      paint();
      announce("지난번 알림의 받는 사람과 글을 채웠어요.");
    }

    // ================= 받는 사람 추천(POST /api/notify/suggest) =================
    async function refreshSuggest() {
      const seq = ++suggestSeq;
      if (!monitoring) return;
      const body = { txn_ids: picked.filter((it) => !it.unsaved).map((it) => it.txn.id).slice(0, 20) };
      // 저장하지 않은 확인 거래(돈 보내기의 안 보낼래요·물어볼래요)는 pending으로 넘겨 이해충돌·등급도 보게 한다(RF-1)
      const unsaved = picked.find((it) => it.unsaved);
      if (unsaved) body.pending = pendingOf(unsaved);
      let d = null;
      try {
        d = await ctx.req("POST", "/api/notify/suggest", body);
      } catch (e) {
        if (e === STALE || seq !== suggestSeq) return;
        if (body.pending && e && e.status === 422) {   // pending을 모르는 옛 엔진: 거래 id만으로 다시 묻는다(돈 받는 조력자는 화면이 기억한 것으로 경고)
          try { d = await ctx.req("POST", "/api/notify/suggest", { txn_ids: body.txn_ids }); } catch (e2) { if (e2 === STALE) return; d = null; }
        }
        if (seq !== suggestSeq || !ctx.alive()) return;
        if (!d) {
          suggestion = null;   // 추천 없이 쓴다(체크는 그대로)
          applySuggestion(true);
          return;
        }
      }
      if (seq !== suggestSeq || !ctx.alive()) return;
      const byId = (list) => new Map((Array.isArray(list) ? list : []).map((x) => [String(x.id), x]));
      suggestion = { helpers: byId(d && d.helpers), counselors: byId(d && d.counselors), due: Boolean(d && d.counseling_due),
        reason: String((d && d.counseling_reason) || (d && d.counseling_due ? "repeat" : "")) };
      applySuggestion(true);
    }

    function sugOf(p) {
      if (!suggestion) return null;
      return (p.kind === "helper" ? suggestion.helpers : suggestion.counselors).get(String(p.id)) || null;
    }
    /** 돈 보내기가 알려 준 이 거래의 돈 받는 조력자 id(추천을 못 받을 때도 경고하게). */
    function knownConflicts() {
      const ids = new Set();
      for (const it of picked) for (const id of it.conflict_ids || []) ids.add(String(id));
      return ids;
    }
    function isConflict(p) {
      if (p.kind !== "helper") return false;
      const s = sugOf(p);
      return Boolean((s && s.conflict) || knownConflicts().has(p.id));
    }
    function isSuggested(p) {
      const s = sugOf(p);
      return Boolean(s && s.suggested && !isConflict(p));
    }
    function chosenCount() { return chosen.size; }
    /** 한도(10명) 안에서만 체크한다. 넘으면 false. */
    function addChosen(key) {
      if (chosen.has(key)) return true;
      if (chosen.size >= MAX_TO) return false;
      chosen.add(key);
      return true;
    }

    /** 추천에 맞춰 체크한다: 본인이 바꾼 사람은 그대로, 돈을 받은 조력자는 체크를 푼다(fresh: 새 추천이 왔을 때).
     * 상담하는 곳은 저절로 체크하지 않는다(추천 배지만). 상담 안내(to=counselors)로 왔을 때만 추천받은 곳을 체크한다. */
    function applySuggestion(fresh) {
      for (const p of helpers) {
        if (isConflict(p)) { if (fresh || !touched.has(p.key)) chosen.delete(p.key); continue; }
        if (!suggestion || touched.has(p.key)) continue;
        if (isSuggested(p)) addChosen(p.key); else chosen.delete(p.key);
      }
      for (const p of counselors) {
        if (!suggestion || touched.has(p.key)) continue;
        if (toCounselors && isSuggested(p)) addChosen(p.key); else chosen.delete(p.key);
      }
      if (suggestion && counselors.some(isSuggested)) counselorsOpen = true;
      if (!fresh) return;
      if (helpersLoaded) renderHelpers();
      if (counselorsLoaded) renderCounselors();
      paint();
      const n = [...helpers, ...counselors].filter((p) => isSuggested(p) && chosen.has(p.key)).length;
      if (n) announce(`추천하는 받는 사람 ${n}명을 미리 골랐어요.`);
    }

    // ================= 1 무엇을 알릴까요 =================
    function renderPicked() {
      if (!monitoring) {
        fill(pickedSlot, h("div", { class: "np-none" },
          h("p", { text: "거래 살펴보기가 꺼져 있어서 거래를 고를 수 없어요. 거래 없이 직접 적을 수 있어요." }),
          h("button", { type: "button", class: "btn sm weak", onclick: () => go("more/consent") }, icon("toggle"), h("span", { text: "동의 켜러 가기" }))));
        return;
      }
      if (!picked.length) {
        fill(pickedSlot, h("p", { class: "np-empty-line", text: "알릴 거래를 골라 주세요. 거래 없이 직접 적어도 돼요." }));
        return;
      }
      fill(pickedSlot,
        h("p", { class: "np-count-line", text: `거래 ${nf.format(picked.length)}건을 알려요.` }),
        h("ul", { class: "np-picked", "aria-label": "알릴 거래" }, picked.map((it) => h("li", { class: "np-pick" },
          pickRow(it),
          h("button", { type: "button", class: "btn sm ghost np-remove", "aria-label": `${it.txn.counterparty || "이름 없음"} ${moneyText(it.txn.amount)} 거래 빼기`,
            onclick: () => removePick(it.txn.id) }, icon("close"), h("span", { text: "빼기" }))))));
    }

    /** 고른 거래·들어온 길을 주소에 남긴다(새로 고치거나 탭을 오가도 고른 거래가 남게, RF-8). */
    function syncUrl() {
      ctx.replaceParams({
        txn: picked.length ? picked.map((it) => it.txn.id).join(",") : null,
        to: toCounselors ? "counselors" : null,
        helper: wantHelpers.size ? [...wantHelpers].join(",") : null,
        ask: askMode ? "1" : null,
        channel: wantChannel || null,
      });
    }

    function removePick(id) {
      picked = picked.filter((it) => it.txn.id !== id);
      syncUrl();
      refreshMessages();
      renderPicked();
      paint();
      refreshSuggest();
      announce(picked.length ? `거래를 뺐어요. ${picked.length}건이 남았어요.` : "거래를 모두 뺐어요.");
      const first = pickedSlot.querySelector(".np-remove") || step1.querySelector("h3");
      if (first) first.focus();
    }

    // 거래 없이 직접 적기: 고른 거래만 뺀다. 직접 고친 글은 묻지 않고 지우지 않는다(FN-03, 글 다시 채우기로 새로 쓸 수 있음)
    function writeDirect() {
      const kept = groupList.filter((g) => g.edited && !g.el.hidden);
      picked = [];
      syncUrl();
      refreshMessages();
      renderPicked();
      paint();
      refreshSuggest();
      if (kept.length) toast("고친 글은 그대로 두었어요. 새 글이 필요하면 글 다시 채우기를 눌러 주세요.");
      const g = groupList.find((x) => !x.el.hidden);
      if (!g) { announce("거래를 뺐어요. 받는 사람을 고르면 글을 적을 수 있어요."); step2.querySelector("h3").focus(); return; }
      g.msg.focus();
      g.msg.setSelectionRange(g.msg.value.length, g.msg.value.length);
      g.msg.scrollIntoView({ block: "center" });
    }

    // ================= 2 누구에게 알릴까요 =================
    function personRow(p) {
      const s = sugOf(p);
      const conflict = isConflict(p);
      const on = chosen.has(p.key);
      const box = h("input", { type: "checkbox", checked: on });
      const row = h("label", { class: `np-person${on ? " on" : ""}${conflict ? " conflict" : ""}` },
        box,
        h("span", { class: "np-kind-ic" }, icon(p.icon)),
        h("span", { class: "row-main" },
          h("span", { class: "row-title" }, h("span", { class: "np-name", text: p.name }),
            s && s.suggested && !conflict ? h("span", { class: "badge info np-rec" }, icon("check-line"), h("span", { text: "추천" })) : null),
          p.sub ? h("span", { class: "row-sub", text: p.sub }) : null,
          h("span", { class: "np-has-row" },
            hasTag("chat", p.phone ? "번호" : "번호 없음", Boolean(p.phone)),
            hasTag("mail", p.email ? "메일" : "메일 없음", Boolean(p.email))),
          conflict ? h("span", { class: "np-conflict" }, icon("warning"),
            h("span", null, splitSentences(CONFLICT_WARN).map((t) => h("span", { class: "sent", text: `${t} ` })))) : null));
      box.addEventListener("change", () => {
        touched.add(p.key);
        if (box.checked && !addChosen(p.key)) { box.checked = false; announce(limitText()); paint(); return; }
        if (!box.checked) chosen.delete(p.key);
        row.classList.toggle("on", box.checked);
        paint();
      });
      rows.set(p.key, { box, row });
      return row;
    }

    function renderHelpers() {
      for (const p of helpers) rows.delete(p.key);
      fill(helperSlot, helpers.length
        ? h("div", { class: "np-people", role: "group", "aria-label": "조력자" }, helpers.map(personRow))
        : h("div", { class: "np-none" },
          h("p", { text: "아직 정한 조력자가 없어요." }),
          h("button", { type: "button", class: "btn sm weak", onclick: () => go("more/helpers") }, icon("plus"), h("span", { text: "조력자 정하기" }))));
    }

    function renderCounselors() {
      for (const p of counselors) rows.delete(p.key);
      fill(counselorSlot, counselors.length
        ? h("div", { class: "np-people", role: "group", "aria-label": "상담하는 곳" }, counselors.map(personRow))
        : h("div", { class: "np-none" },
          h("p", { text: "아직 정한 상담하는 곳이 없어요." }),
          h("button", { type: "button", class: "btn sm weak", onclick: () => go("more/counselors") }, icon("plus"), h("span", { text: "상담하는 곳 정하기" }))));
      if (counselors.length) {
        counselorSlot.append(h("button", { type: "button", class: "btn sm ghost np-manage", onclick: () => go("more/counselors") },
          icon("edit"), h("span", { text: "상담하는 곳 고치기" })));
      }
    }

    function paintCounselorToggle() {
      counselorToggle.setAttribute("aria-expanded", counselorsOpen ? "true" : "false");
      counselorSlot.hidden = !counselorsOpen;
      const n = counselors.filter((p) => chosen.has(p.key)).length;
      const picks = n ? ` · ${nf.format(n)}곳 고름` : "";
      setText(counselorToggle.querySelector(".np-expand-text"),
        counselors.length ? `상담하는 곳 ${nf.format(counselors.length)}곳${picks}` : "상담하는 곳");
    }

    function people(kind) { return [...helpers, ...counselors].filter((p) => p.kind === kind && chosen.has(p.key)); }
    function limitText() { return `한 번에 ${MAX_TO}명까지 보낼 수 있어요. 다른 사람을 고르려면 먼저 체크를 풀어 주세요.`; }

    // ================= 3 어떻게 보낼까요 =================
    /** 받는 사람 무리 하나(방법·글·앱 열기)의 칸. 한 번 만들어 두고 paint가 글·상태만 바꾼다(쓰던 글·초점이 사라지지 않게). */
    function makeGroup(kind) {
      const def = GROUPS[kind];
      const sfx = kind === "helper" ? "" : "-c";
      const g = { kind, def, sfx, channel: "", chosenWay: false, edited: false, base: null, radios: {}, sig: "", buttons: new Map() };
      g.title = h("h4", { class: "np-g-title", id: `np-g-${kind}` });
      g.names = h("p", { class: "np-g-names" });
      g.channelGroup = h("div", { class: "segmented np-channels", role: "radiogroup", "aria-labelledby": `np-g-${kind}` },
        def.ways.map((w) => {
          g.radios[w] = h("input", { type: "radio", name: `np-channel${sfx}`, value: w, "aria-describedby": `np-why${sfx}-${w}`,
            onchange: () => { g.channel = w; g.chosenWay = true; refreshMessage(g); paint(); } });
          return h("label", null, g.radios[w], h("span", null, icon(CHANNELS[w].icon), h("span", { text: CHANNELS[w].label })));
        }));
      g.reasons = h("ul", { class: "np-reasons" });
      g.missing = h("p", { class: "np-missing", hidden: true });
      g.msgLabel = h("label", { class: "field-label np-msg-label", for: `np-msg${sfx}` });
      g.msg = h("textarea", { class: "input np-msg", id: `np-msg${sfx}`, rows: "6", maxlength: String(MAX_MESSAGE),
        "aria-describedby": `np-msg${sfx}-hint np-msg${sfx}-count`, ...NO_CHECK, autocomplete: "off" });
      g.count = h("span", { class: "hint np-count", id: `np-msg${sfx}-count` });
      g.refill = h("button", { type: "button", class: "btn sm ghost", hidden: true,
        onclick: () => { g.edited = false; setGuard(); setMsg(g, autoText(g)); paint(); announce("글을 다시 채웠어요."); } },
      icon("refresh"), h("span", { text: "글 다시 채우기" }));
      g.subject = h("p", { class: "np-subject", hidden: true });
      g.hint = h("p", { class: "hint", id: `np-msg${sfx}-hint` });
      // 보낼 글을 소리로 듣고 확인한다(AUG-08). 음성이 없으면 버튼이 없다
      g.speak = speakButton(() => g.msg.value.replace(/\[SafePause\]\s*/g, "SafePause. "), { cls: "btn sm weak np-speak", label: "보낼 글 소리로 듣기" });
      g.fail = h("div", { class: "np-fail", role: "alert" });
      g.btns = h("div", { class: "np-send-btns" });
      g.doneLine = h("p", { class: "np-done", role: "status", hidden: true });
      g.copy = h("button", { type: "button", class: "btn ghost block np-copy", onclick: (e) => copyMessage(g, e.currentTarget) }, icon("copy"), h("span", { text: "글만 복사하기" }));
      g.nameInput = null;
      let nameField = null;
      if (kind === "counselor") {
        g.nameInput = h("input", { class: "input", id: "np-myname", type: "text", maxlength: String(MAX_NAME), value: myName,
          ...NO_CHECK, autocomplete: "off", "aria-describedby": "np-myname-hint" });
        g.nameInput.addEventListener("input", () => {
          myName = g.nameInput.value.trim().slice(0, MAX_NAME);
          saveMyName(myName);
          refreshMessage(g);
          paint();
        });
        nameField = h("div", { class: "field np-myname" }, h("label", { for: "np-myname", text: "내 이름 (적지 않아도 돼요)" }), g.nameInput,
          h("p", { class: "hint", id: "np-myname-hint", text: `상담하는 곳에 보내는 글 첫머리에 들어가요. ${deviceWord()}에만 기억해요.` }));
      }
      g.msg.addEventListener("input", () => { g.edited = g.msg.value !== autoText(g); setGuard(); fitMessage(g); paintGroupText(g); paintButtons(g); });
      g.el = h("section", { class: "np-group", "data-kind": kind, "aria-labelledby": `np-g-${kind}`, hidden: true },
        h("div", { class: "np-g-head" }, h("span", { class: "row-icon blue" }, icon(def.icon)), h("div", { class: "np-g-main" }, g.title, g.names)),
        g.channelGroup, g.reasons, g.missing,
        nameField,
        g.msgLabel, g.msg, h("div", { class: "np-msg-foot" }, g.count, g.refill), g.subject, g.hint, g.speak,
        g.fail, g.btns, g.doneLine, g.copy);
      return g;
    }

    function autoText(g) {
      return g.kind === "helper" ? helperText(picked, askMode) : counselText(picked, myName, g.channel === "call");
    }
    function setMsg(g, text) { g.msg.value = text; fitMessage(g); }
    function refreshMessage(g) { if (!g.edited) setMsg(g, autoText(g)); }
    function refreshMessages() { for (const g of groupList) refreshMessage(g); }
    // 글 길이에 맞춰 칸 높이를 늘린다(안에서 따로 스크롤하지 않게)
    function fitMessage(g) {
      if (!g.msg.isConnected || g.el.hidden) return;
      g.msg.style.height = "auto";
      if (g.msg.scrollHeight) g.msg.style.height = `${g.msg.scrollHeight + 4}px`;
    }
    function subjectOf(g) {
      if (g.kind === "counselor") return SUBJECT_COUNSEL;
      if (!picked.length) return SUBJECT_DIRECT;
      return askMode ? SUBJECT_ASK : SUBJECT;
    }
    function wayOrder(g) {
      if (g.kind === "counselor") return ["call", "sms", "email"];
      return wantChannel ? [wantChannel, ...g.def.ways.filter((w) => w !== wantChannel)] : g.def.ways;
    }

    /** 이 방법을 쓸 수 있는지와 못 쓰는 이유. sel = 이 무리에서 고른 받는 사람. */
    function wayState(g, way, sel) {
      const whom = `고른 ${g.def.title}${g.def.to}`;
      if (way === "sms") {
        if (!caps.sms) return { ok: false, why: "문자는 휴대폰 앱에서 보낼 수 있어요." };
        const to = sel.filter((p) => p.phone);
        if (sel.length && !to.length) return { ok: false, why: `${whom} ${g.kind === "helper" ? "휴대폰 번호" : "번호"}가 없어요.` };
        return { ok: true, to, lack: sel.filter((p) => !p.phone) };
      }
      if (way === "email") {
        if (!caps.email) return { ok: false, why: `${deviceWord()}에서는 메일 앱을 열 수 없어요.` };
        const to = sel.filter((p) => p.email);
        if (sel.length && !to.length) return { ok: false, why: `${whom} 메일 주소가 없어요.` };
        return { ok: true, to, lack: sel.filter((p) => !p.email) };
      }
      if (!caps.call) return { ok: false, why: "전화는 휴대폰 앱에서 걸 수 있어요." };
      const to = sel.filter((p) => p.phone);
      if (sel.length && !to.length) return { ok: false, why: "고른 곳에 전화번호가 없어요." };
      return { ok: true, to, lack: sel.filter((p) => !p.phone) };
    }

    /** 고른 것에 맞춰 추천 줄·한도·무리마다 방법·글 안내·앱 열기 버튼을 다시 그린다. */
    function paint() {
      recLine.hidden = !helpers.some(isSuggested);
      if (!recLine.hidden) setText(recLine, "조력자 설정에 맞는 사람을 추천해요. 바꿔도 돼요.");
      const counselRecs = counselors.filter(isSuggested);
      counselRec.hidden = !counselRecs.length || !counselorsOpen;
      if (counselRecs.length) {
        const why = suggestion && suggestion.reason === "conflict" ? "알릴 조력자가 모두 돈을 받은 사람이라 상담하는 곳을 추천해요."
          : "꼭 확인할 거래가 자주 있어서 상담하는 곳을 추천해요.";
        setText(counselRec, toCounselors ? `${why} 추천하는 곳을 골라 두었어요. 바꿔도 돼요.` : `${why} 알리려면 직접 골라 주세요.`);
      }
      // 받는 사람 한도: 10명을 고르면 나머지 칸을 끄고 알린다(FN-06·FE-07)
      const full = chosenCount() >= MAX_TO;
      for (const [key, r] of rows) {
        if (!r.box.isConnected) { rows.delete(key); continue; }
        r.box.disabled = full && !chosen.has(key);
        r.row.classList.toggle("off", r.box.disabled);
      }
      limitLine.hidden = !full;
      if (full) setText(limitLine, limitText());
      for (const g of groupList) paintGroup(g);
      emptyLine.hidden = groupList.some((g) => !g.el.hidden);
      paintCounselorToggle();
    }

    function paintGroup(g) {
      const sel = people(g.kind);
      const wasHidden = g.el.hidden;
      g.el.hidden = !sel.length;
      if (!sel.length) return;
      const states = Object.fromEntries(g.def.ways.map((w) => [w, wayState(g, w, sel)]));
      const prev = g.channel;
      const order = wayOrder(g);
      if (!g.chosenWay || !states[g.channel] || !states[g.channel].ok) g.channel = order.find((w) => states[w].ok) || g.channel || order[0];
      if (prev !== g.channel) refreshMessage(g);   // 전화로 말할 내용과 보낼 글은 다르다
      for (const w of g.def.ways) {
        g.radios[w].disabled = !states[w].ok;
        g.radios[w].checked = w === g.channel;
      }
      fill(g.reasons, g.def.ways.filter((w) => !states[w].ok).map((w) =>
        h("li", { id: `np-why${g.sfx}-${w}` }, icon("info"), h("span", { text: states[w].why }))));
      const st = states[g.channel];
      const lack = st.ok ? st.lack : [];
      g.missing.hidden = !lack.length;
      if (lack.length) {
        const what = g.channel === "email" ? "메일 주소" : g.channel === "call" ? "전화번호" : g.kind === "helper" ? "휴대폰 번호" : "번호";
        setText(g.missing, `${lack.map((p) => p.name).join(", ")}${g.def.to}는 ${what}가 없어서 가지 않아요.`);
      }
      setText(g.title, `${g.def.title} ${nf.format(sel.length)}${g.def.unit}${g.def.to}`);
      setText(g.names, sel.map((p) => p.name).join(", "));
      g.copy.hidden = g.channel === "call";
      paintGroupText(g);
      paintButtons(g);
      if (wasHidden) fitMessage(g);
    }

    function paintGroupText(g) {
      const call = g.channel === "call";
      setText(g.msgLabel, call ? "전화로 말할 내용" : "보낼 글");
      g.subject.hidden = g.channel !== "email";
      if (!g.subject.hidden) fill(g.subject, h("span", { class: "np-subject-label", text: "메일 제목" }), h("span", { class: "np-subject-text", text: subjectOf(g) }));
      setText(g.hint, call ? "전화 걸기 화면만 열어요. 전화는 직접 걸어요. 이 글을 보며 말하면 돼요." : "받는 사람이 읽기 쉽게 고쳐도 돼요.");
      g.count.textContent = `${nf.format(g.msg.value.length)} / ${nf.format(MAX_MESSAGE)}자`;
      g.refill.hidden = !g.edited;
    }

    /** 앱 열기 버튼: 조력자는 한 번에, 상담하는 곳은 전화면 곳마다(다이얼 화면은 번호 하나), 글이면 한 번에. */
    function actionsOf(g) {
      const sel = people(g.kind);
      const st = wayState(g, g.channel, sel);
      const ch = CHANNELS[g.channel];
      if (g.channel === "call") {
        return (st.ok ? st.to : sel).map((p) => ({ key: `call:${p.key}`, target: p, who: `${p.name}에`, what: "전화하기", icon: ch.icon }));
      }
      const to = st.ok ? st.to : sel;
      const who = to.length === 1 ? `${to[0].name}${g.def.to}` : `${g.def.title} ${nf.format(to.length)}${g.def.unit}${g.def.to}`;
      return [{ key: g.kind, target: null, who, what: `${ch.label} 보내기`, icon: ch.icon }];
    }

    function paintButtons(g) {
      if (g.el.hidden) return;
      const acts = actionsOf(g);
      const sel = people(g.kind);
      const st = wayState(g, g.channel, sel);
      const sig = `${g.channel}|${acts.map((a) => a.key).join(",")}`;
      if (sig !== g.sig) {
        g.sig = sig;
        g.buttons = new Map();
        fill(g.btns, acts.map((a, i) => {
          const b = h("button", { type: "button", class: `btn ${i === 0 ? "primary" : "weak"} big block np-send-btn`,
            onclick: (e) => sendAction(g, a.target, e.currentTarget) }, h("span", { class: "btn-ic" }, icon(a.icon)),
          // 받는 사람(긴 기관 이름)과 할 일을 두 줄로: 조사가 다음 줄 앞에 홀로 남지 않게
          h("span", { class: "np-send-text" }, h("span", { class: "np-send-who" }), h("span", { class: "np-send-what" })));
          g.buttons.set(a.key, b);
          return b;
        }));
      }
      const ready = sel.length > 0 && st.ok && (g.channel === "call" || g.msg.value.trim().length > 0);
      for (const a of acts) {
        const b = g.buttons.get(a.key);
        if (!b) continue;
        b.querySelector(".np-send-who").textContent = `${a.who} `;
        b.querySelector(".np-send-what").textContent = a.what;
        b.setAttribute("aria-disabled", ready && (!a.target || a.target.phone) ? "false" : "true");
        b.classList.toggle("done", done.has(a.key));
      }
      const opened = acts.filter((a) => done.has(a.key));
      g.doneLine.hidden = !opened.length;
      if (opened.length) {
        setText(g.doneLine, g.channel === "call"
          ? `${opened.map((a) => a.target.name).join(", ")}에 전화 걸기 화면을 열었어요.`
          : `${CHANNELS[g.channel].app}을 열었어요. 보낸 알림에 적어 두었어요.`);
      }
    }

    /** 아직 앱을 열지 않은 받는 사람 무리가 있는지(모두 열었으면 보낸 알림으로 간다). */
    function allDone() {
      const keys = groupList.filter((g) => people(g.kind).length).flatMap((g) => actionsOf(g).map((a) => a.key));
      return keys.length > 0 && keys.every((k) => done.has(k));
    }

    // ---- 보내기: 앱 열기 → 기록 → (모두 열었으면) 알림 탭 ----
    async function sendAction(g, target, btn) {
      if (btn.getAttribute("aria-busy") === "true") return;
      const sel = people(g.kind);
      const st = wayState(g, g.channel, sel);
      const message = g.msg.value.trim();
      const ch = CHANNELS[g.channel];
      if (!sel.length) { toast("알릴 사람을 골라 주세요.", "error"); step2.querySelector("h3").focus(); step2.scrollIntoView({ block: "start" }); return; }
      if (!st.ok) { toast(st.why, "error"); step3.querySelector("h3").focus(); return; }
      if (g.channel !== "call" && !message) { toast("보낼 글을 적어 주세요.", "error"); g.msg.focus(); return; }
      if (target && !target.phone) { toast("고른 곳에 전화번호가 없어요.", "error"); return; }
      const risky = sel.filter(isConflict);
      if (risky.length) {
        const ok = await confirmSheet({
          title: "돈을 받은 사람에게도 알릴까요?",
          lines: [`${risky.map((p) => p.name).join(", ")}: ${splitSentences(CONFLICT_WARN)[0]}`, ...splitSentences(CONFLICT_WARN).slice(1)],
          confirmText: "그래도 보낼래요", cancelText: "다시 고를래요",
        });
        if (!ok) { step2.querySelector("h3").focus(); return; }
      }
      const to = target ? [target] : st.to.slice(0, MAX_TO);
      const uri = g.channel === "sms" ? smsUri(to.map((p) => p.phone), message)
        : g.channel === "email" ? mailtoUri(to.map((p) => p.email), subjectOf(g), message)
          : telUri(target.phone);
      g.fail.replaceChildren();
      if (!openExternal(uri)) {
        fill(g.fail, h("div", { class: "notice red" }, icon("warning"), h("div", null,
          h("p", { text: `${deviceWord()}에서 ${ch.app}을 열지 못했어요. 글을 복사해서 직접 보내 주세요.` }),
          h("button", { type: "button", class: "btn sm weak notice-action", onclick: (e) => copyMessage(g, e.currentTarget) }, icon("copy"), h("span", { text: "글 복사하기" })))));
        g.fail.scrollIntoView({ block: "center" });
        return;
      }
      btn.setAttribute("aria-busy", "true");
      const ok = await record(g.channel, to, message || `${target.name}에 전화 걸기 화면을 열었어요.`);
      if (!btn.isConnected) return;
      btn.removeAttribute("aria-busy");
      if (!ok) return;
      done.add(target ? `call:${target.key}` : g.kind);
      if (allDone()) {
        for (const x of groupList) x.edited = false;
        setGuard();
        toast(`${ch.app}을 열었어요. 보낸 알림에 적어 두었어요.`);
        go("alerts?tab=sent", { replace: true });   // 뒤로 가기로 같은 글이 채워진 화면에 돌아와 두 번 보내지 않게(RF-12)
        return;
      }
      paint();
      toast(`${ch.app}을 열었어요. 보낸 알림에 적어 두었어요. 남은 받는 사람에게도 보내 주세요.`);
      const next = groupList.flatMap((x) => (people(x.kind).length ? [...x.buttons.entries()] : [])).find(([k]) => !done.has(k));
      if (next) next[1].focus();
    }

    async function record(ch, to, message) {
      try {
        await ctx.req("POST", "/api/notices/record", {
          channel: ch,
          recipients: to.slice(0, MAX_TO).map((p) => ({ kind: p.kind, id: p.id, name: String(p.name).slice(0, 30) })),
          txn_ids: picked.map((it) => it.txn.id).slice(0, 20),
          message: message.slice(0, MAX_MESSAGE),
        });
        return true;
      } catch (e) {
        if (e !== STALE) toast("보낸 기록을 남기지 못했어요. 잠시 뒤 다시 해 주세요.", "error");
        return false;
      }
    }

    async function copyMessage(g, btn) {
      const message = g.msg.value.trim();
      if (!message) { toast("보낼 글을 적어 주세요.", "error"); g.msg.focus(); return; }
      if (btn && btn.getAttribute("aria-busy") === "true") return;
      const ok = await copyText(message);
      if (!ok) {
        // 직접 복사하기 쉽게 보낼 글을 모두 골라 둔다
        g.msg.focus();
        g.msg.select();
        g.msg.scrollIntoView({ block: "center" });
        toast("글을 복사하지 못했어요. 골라 둔 글을 길게 눌러 복사해 주세요.", "error");
        return;
      }
      toast("글을 복사했어요. 문자나 메일에 붙여 넣어 주세요.");
      const sel = people(g.kind);
      if (sel.length && g.lastCopied !== message) {   // 같은 글은 한 번만 기록한다
        if (btn) btn.setAttribute("aria-busy", "true");
        if (await record("copy", sel, message)) g.lastCopied = message;
        if (btn && btn.isConnected) btn.removeAttribute("aria-busy");
      }
    }

    // ================= 거래 고르기 시트: 꼭 확인할 거래 · 걱정되는 거래 · 담은 거래 =================
    // 확인 버튼은 시트 아래에 붙어 있다(목록이 길어도 늘 보임, L2). 목록은 50건씩 더 불러온다(FN-05)
    function openPicker() {
      let draft = picked.slice();
      const data = {};
      let view = "high";
      const panel = h("div", { class: "np-pick-panel" }, skeleton(2));
      const doneText = h("span");
      const doneBtn = h("button", { type: "button", class: "btn primary big block" }, doneText);
      const chipBtns = PICK_TABS.map((t) => h("button", {
        type: "button", class: "chip", "data-v": t.value, "aria-pressed": "false",
        onclick: () => { view = t.value; paintChips(); show(); const line = panel.querySelector(".np-pick-total"); if (line) announce(line.textContent); },
      }, h("span", { text: t.label })));
      const chips = h("div", { class: "chips np-pick-chips", role: "group", "aria-label": "거래 보기" }, chipBtns);

      function paintChips() { for (const b of chipBtns) b.setAttribute("aria-pressed", b.dataset.v === view ? "true" : "false"); }
      function paintDone() { doneText.textContent = draft.length ? `${nf.format(draft.length)}건 고르기` : "고르지 않기"; }

      function rowOf(it) {
        const on = draft.some((x) => x.txn.id === it.txn.id);
        const box = h("input", { type: "checkbox", checked: on });
        const row = h("label", { class: `np-check${on ? " on" : ""}` }, box, pickRow(it));
        box.addEventListener("change", () => {
          if (box.checked && draft.length >= MAX_PICK) {
            box.checked = false;
            toast(`한 번에 ${MAX_PICK}건까지 고를 수 있어요.`, "error");
            return;
          }
          draft = box.checked ? [...draft, it] : draft.filter((x) => x.txn.id !== it.txn.id);
          row.classList.toggle("on", box.checked);
          paintDone();
        });
        return row;
      }

      function show(focusFrom = -1) {
        const t = PICK_TABS.find((x) => x.value === view);
        const d = data[view];
        if (!d) { fill(panel, skeleton(2)); return; }
        if (d.error && !d.items.length) { fill(panel, errorNotice(friendlyError(d.error), go)); return; }
        if (!d.items.length) {
          fill(panel, h("div", { class: "empty" }, icon(view === "flags" ? "bookmark" : "check-line"),
            h("b", { text: view === "flags" ? "담은 거래가 없어요" : `${t.label}가 없어요` }),
            h("p", { text: view === "flags" ? "내 거래에서 거래를 누르면 알림 목록에 담을 수 있어요." : "다른 보기를 골라 보세요." })));
          return;
        }
        const list = h("div", { class: "np-pick-list", role: "group", "aria-label": t.label }, d.items.map(rowOf));
        const left = d.total - d.items.length;
        fill(panel, h("p", { class: "np-pick-total", text: left > 0
          ? `${t.label} ${nf.format(d.total)}건 가운데 최근 ${nf.format(d.items.length)}건이에요.`
          : `${t.label} ${nf.format(d.total)}건이에요.` }),
        list,
        d.error ? errorNotice(friendlyError(d.error), go) : null,
        left > 0 && view !== "flags" ? h("button", { type: "button", class: "btn weak block np-pick-more",
          onclick: (e) => busyMore(e.currentTarget, view) }, icon("chevron-down"), h("span", { text: `${nf.format(Math.min(PAGE, left))}건 더 보기` })) : null);
        if (focusFrom >= 0) {
          const box = list.querySelectorAll("input")[focusFrom];
          if (box) box.focus();
        }
      }

      async function load(v, offset) {
        const t = PICK_TABS.find((x) => x.value === v);
        const path = v === "flags" ? t.path : `${t.path}&limit=${PAGE}&offset=${offset}`;
        try {
          const d = await ctx.req("GET", path);
          const items = v === "flags" ? (d.items || []).map((x) => x.item).filter(Boolean) : (d.items || []);
          const prev = offset && data[v] ? data[v].items : [];
          const seen = new Set(prev.map((x) => x.txn.id));
          data[v] = { items: [...prev, ...items.filter((x) => !seen.has(x.txn.id))],
            total: v === "flags" ? items.length : (d.matched ?? (prev.length + items.length)) };
          // 꼭 확인할 거래가 없으면 걱정되는 거래부터 보인다
          if (v === "high" && !offset && !items.length && view === "high") { view = "caution"; paintChips(); }
        } catch (e) {
          if (e === STALE) return false;
          data[v] = { ...(data[v] || { items: [], total: 0 }), error: e };
        }
        return true;
      }

      async function busyMore(btn, v) {
        if (btn.getAttribute("aria-busy") === "true") return;
        btn.setAttribute("aria-busy", "true");
        btn.setAttribute("aria-disabled", "true");
        const from = data[v].items.length;
        if (!(await load(v, from))) return;
        if (sheet.el.isConnected && view === v) { show(from); announce(`거래를 더 불러왔어요. 모두 ${nf.format(data[v].items.length)}건이에요.`); }
      }

      const sheet = openSheet((close) => {
        doneBtn.addEventListener("click", () => {
          picked = draft.slice(0, MAX_PICK);
          syncUrl();
          refreshMessages();
          renderPicked();
          paint();
          close();
          refreshSuggest();
          announce(picked.length ? `거래 ${picked.length}건을 골랐어요.` : "거래를 고르지 않았어요.");
        });
        return [
          h("h2", { class: "sheet-title focus-target", tabindex: "-1", text: "어떤 거래를 알릴까요?" }),
          h("p", { class: "sheet-sub", text: `한 번에 ${MAX_PICK}건까지 고를 수 있어요.` }),
          chips, panel,
          h("div", { class: "sheet-actions np-pick-actions" }, doneBtn,
            h("button", { type: "button", class: "btn big block", text: "닫기", onclick: () => close() })),
        ];
      }, { label: "거래 고르기", className: "np-pick-sheet" });
      paintChips();
      paintDone();

      if (!monitoring) {
        fill(panel, h("div", { class: "empty" }, icon("toggle"),
          h("b", { text: "거래 살펴보기가 꺼져 있어요" }),
          h("p", { text: "거래 살펴보기를 켜면 거래를 고를 수 있어요." })));
        return;
      }
      // 세 목록을 함께 불러 둔다(칩을 바꾸면 바로 보이게)
      for (const t of PICK_TABS) {
        load(t.value, 0).then((fresh) => { if (fresh && sheet.el.isConnected && (view === t.value || t.value === "high")) show(); });
      }
    }

    function retryBox(e, again) {
      return h("div", null, errorNotice(friendlyError(e), go),
        h("button", { type: "button", class: "btn sm weak", onclick: () => again() }, icon("refresh"), h("span", { text: "다시 불러오기" })));
    }
  },
};

/** 날짜 머리 없이 보이는 거래 줄(고른 거래·거래 고르기): 이름과 금액을 한 줄에, 날짜·방법, 표시 이름. */
function pickRow(item) {
  const t = item.txn;
  const out = t.direction === "out";
  const tone = item.level === "high" ? "red" : item.level === "caution" ? "orange" : out ? "" : "blue";
  const tags = [item.level && item.level !== "none" ? levelBadge(item.level) : null,
    ...txnSignals(item).map((s) => h("span", { class: "tag" }, icon(s.icon), h("span", { text: s.text }))),
    flagBadge(item), reviewBadge(item), notifiedBadge(item), item.practice ? checkedBadge() : null].filter(Boolean);
  return h("span", { class: "np-txn" },
    h("span", { class: `row-icon ${tone}`.trim() }, icon(CHANNEL_ICON[t.channel] || "cash")),
    h("span", { class: "np-txn-main" },
      h("span", { class: "np-txn-top" },
        h("span", { class: "row-title", text: t.counterparty || "(이름 없음)" }),
        h("span", { class: `row-amount${out ? "" : " in"}`, text: txnAmount(t) })),
      subParts([whenText(t.ts), CHANNEL_KO[t.channel] || t.channel]),
      tags.length ? h("span", { class: "row-tags" }, tags) : null));
}

/** 번호 단계 카드. h3에 id를 붙여 묶음 이름으로 쓴다. */
function stepCard(no, id, title, ...children) {
  return h("section", { class: "card np-step", "aria-labelledby": id },
    h("div", { class: "np-step-head" },
      h("span", { class: "np-step-no", "aria-hidden": "true", text: String(no) }),
      h("h3", { id, tabindex: "-1", text: title })),
    children);
}

/** 연락처가 있는지 표시(아이콘 + 글, 색만으로 구별하지 않음). */
function hasTag(ic, text, on) {
  return h("span", { class: `np-has${on ? "" : " off"}` }, icon(ic), h("span", { text }));
}
