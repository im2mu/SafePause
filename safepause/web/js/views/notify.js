/* 알림 보내기(보내기 탭의 둘째 탭, #/send?mode=notify): 무엇을 → 누구에게 → 어떻게 → 보낼 글 → 문자·메일 앱 열기.
 * - SafePause가 직접 보내지 않는다. 글을 채운 문자·메일 앱(전화는 다이얼 화면)을 열고, 보내기는 사람이 누른다.
 * - 앱을 열면 보낸 알림 기록을 남긴다(POST /api/notices/record, 번호·메일 원본은 서버가 넣지 않음) → 알림 탭 보낸 알림.
 * - 주소 뒤 값: txn=<거래 id>(여러 번 가능)이면 그 거래를 미리 고르고, to=counselors면 상담하는 곳을 펼쳐 둔다.
 *   helper=<조력자 id>(여러 번 가능, 돈 보내기에서 물어볼 사람으로 고른 사람)는 미리 체크한다.
 * - 받는 사람 추천: 거래를 고르거나 바꿀 때 POST /api/notify/suggest로 조력자 설정(알릴 등급·범위·자동으로 알리기)에 맞는
 *   사람을 미리 체크하고 추천 배지를 단다. 그 거래에서 돈을 받은 조력자는 체크를 풀고 경고한다. 그래도 체크하면 보내기 전에
 *   한 번 더 묻는다(본인 결정). 추천을 못 받으면(옛 엔진·동의 꺼짐·오류) 추천 없이 그대로 쓴다.
 * - 보내기 탭(send.js)이 이 화면의 ctx를 따로 만들어 넘긴다(ctx.main = 탭 칸).
 */
import { h, icon, fill, setText, splitSentences, openSheet, confirmSheet, toast, announce, skeleton } from "../ui.js";
import { txnSignals, txnAmount, levelBadge, flaggedBadge, checkedBadge, errorNotice, subParts } from "../components.js";
import { moneyText, formatTime, parseTs, nf, deviceWord } from "../format.js";
import { CHANNEL_KO, CHANNEL_ICON, COUNSELOR_KIND_KO, COUNSELOR_KIND_ICON } from "../labels.js";
import { capabilities, openExternal, smsUri, mailtoUri, telUri, copyText } from "../native.js";
import { STALE } from "../api.js";
import { checkedItem } from "./money.js";

const MAX_PICK = 5;          // 한 번에 알릴 거래(문자 한 통에 읽기 좋은 만큼)
const MAX_MESSAGE = 1000;    // api MAX_NOTICE_MESSAGE
const MAX_TO = 10;           // api MAX_NOTICE_RECIPIENTS
const NO_CHECK = { spellcheck: "false", autocorrect: "off", autocapitalize: "off" };
const CHANNELS = [
  { value: "sms", label: "문자", icon: "chat", open: "문자 앱 열기", app: "문자 앱" },
  { value: "email", label: "메일", icon: "mail", open: "메일 앱 열기", app: "메일 앱" },
  { value: "call", label: "전화", icon: "call", open: "전화 걸기 화면 열기", app: "전화 걸기 화면" },
];
const SUBJECT = "[SafePause] 걱정되는 거래 알림";
const SUBJECT_DIRECT = "[SafePause] 도움이 필요해요";
const DIRECT_TEXT = "[SafePause] 돈 문제로 도움이 필요해서 알려요.\n";
const CONFLICT_WARN = "이 거래에서 돈을 받은 사람이에요. 다른 사람에게 알리는 게 좋아요.";
const PICK_TABS = [
  { value: "high", label: "꼭 확인할 거래", path: "/api/transactions?level=high&limit=50" },
  { value: "caution", label: "걱정되는 거래", path: "/api/transactions?level=caution&limit=50" },
  { value: "flags", label: "담은 거래", path: "/api/flags" },
];

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

function autoMessage(picked) {
  if (!picked.length) return DIRECT_TEXT;
  if (picked.length === 1) return `[SafePause] 걱정되는 거래가 있어 알려요.\n${txnLine(picked[0])}\n확인해 주세요.`;
  return [`[SafePause] 걱정되는 거래 ${picked.length}건이 있어 알려요.`,
    ...picked.map((it, i) => `${i + 1}) ${txnLine(it)}`), "확인해 주세요."].join("\n");
}

/** 404인데 쉬운 말 안내가 없으면(새 기능을 아직 못 쓰는 엔진) 쉬운 말로 바꾼다. */
function friendlyError(e) {
  if (e && e.status === 404 && !/[가-힣]/.test(String(e.message || ""))) {
    return Object.assign(new Error("이 목록을 아직 불러올 수 없어요. 잠시 뒤 다시 해 주세요."), { status: 404 });
  }
  return e;
}

export default {
  title: "알림 보내기",
  tab: "send",
  async render(ctx) {
    const { main, go } = ctx;
    const caps = capabilities();
    const params = ctx.params;
    const wantIds = params.getAll("txn").filter(Boolean).slice(0, MAX_PICK);
    const toCounselors = params.get("to") === "counselors";
    const wantHelpers = new Set(params.getAll("helper").filter(Boolean));

    let picked = [];            // 고른 거래(_item 형식)
    let helpers = [];
    let counselors = [];
    const chosen = new Set();   // 고른 받는 사람 key("helper:h1", "counselor:c1")
    let channel = caps.sms ? "sms" : "email";
    let edited = false;         // 보낼 글을 직접 고쳤는지(고쳤으면 거래를 바꿔도 글을 덮어쓰지 않음)
    let lastCopied = "";
    let counselorsOpen = toCounselors;
    let monitoring = true;      // 거래 살펴보기 동의(꺼져 있으면 거래를 부르지 않고 직접 적기만)
    let suggestion = null;      // 받는 사람 추천 {helpers: Map, counselors: Map, due}. 못 받으면 null(추천 없이)
    let suggestSeq = 0;
    const touched = new Set();  // 본인이 직접 체크를 바꾼 받는 사람(추천이 덮어쓰지 않음)

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
    const counselorToggle = h("button", { type: "button", class: "np-expand", "aria-controls": "np-counselors", "aria-expanded": "false", onclick: () => { counselorsOpen = !counselorsOpen; paintCounselorToggle(); } },
      h("span", { class: "np-expand-main" }, icon("building"), h("span", { class: "np-expand-text", text: "상담하는 곳" })),
      icon("chevron-down", "np-chev"));
    const step2 = stepCard(2, "np-s2", "누구에게 알릴까요?",
      recLine,
      h("div", { class: "np-group-title" }, h("span", { text: "조력자" })),
      helperSlot,
      h("div", { class: "np-divider", "aria-hidden": "true" }),
      counselorToggle, counselorSlot);

    // ---- 3 어떻게 보낼까요 ----
    const radios = {};
    const channelGroup = h("div", { class: "segmented np-channels", role: "radiogroup", "aria-labelledby": "np-s3" },
      CHANNELS.map((c) => {
        radios[c.value] = h("input", { type: "radio", name: "np-channel", value: c.value, "aria-describedby": `np-why-${c.value}`,
          onchange: () => { channel = c.value; paint(); } });
        return h("label", null, radios[c.value], h("span", null, icon(c.icon), h("span", { text: c.label })));
      }));
    const reasons = h("ul", { class: "np-reasons" });
    const missing = h("p", { class: "np-missing", hidden: true });
    const step3 = stepCard(3, "np-s3", "어떻게 보낼까요?", channelGroup, reasons, missing);

    // ---- 4 보낼 글 ----
    const msg = h("textarea", { class: "input np-msg", id: "np-msg", rows: "7", maxlength: String(MAX_MESSAGE), "aria-labelledby": "np-s4",
      "aria-describedby": "np-msg-hint np-msg-count", ...NO_CHECK, autocomplete: "off" });
    const msgHint = h("p", { class: "hint", id: "np-msg-hint" });
    const msgCount = h("span", { class: "hint np-count", id: "np-msg-count" });
    const refill = h("button", { type: "button", class: "btn sm ghost", hidden: true, onclick: () => { edited = false; setGuard(); setMessage(autoMessage(picked)); paint(); announce("글을 다시 채웠어요."); } },
      icon("refresh"), h("span", { text: "글 다시 채우기" }));
    msg.addEventListener("input", () => { edited = msg.value !== autoMessage(picked); setGuard(); fitMessage(); paint(); });
    function setMessage(text) { msg.value = text; fitMessage(); }
    // 글 길이에 맞춰 칸 높이를 늘린다(안에서 따로 스크롤하지 않게)
    function fitMessage() {
      if (!msg.isConnected) return;
      msg.style.height = "auto";
      if (msg.scrollHeight) msg.style.height = `${msg.scrollHeight + 4}px`;
    }
    const step4 = stepCard(4, "np-s4", "보낼 글", msg, h("div", { class: "np-msg-foot" }, msgCount, refill), msgHint);

    // ---- 5 앱 열기 ----
    const sendIc = h("span", { class: "btn-ic" });
    const sendText = h("span");
    const sendBtn = h("button", { type: "button", class: "btn primary big block np-send-btn", onclick: send }, sendIc, sendText);
    const failSlot = h("div", { class: "np-fail", role: "alert" });
    const copyBtn = h("button", { type: "button", class: "btn ghost block", onclick: () => copyMessage(copyBtn) }, icon("copy"), h("span", { text: "글만 복사하기" }));
    const sendArea = h("section", { class: "np-send", "aria-label": "앱 열기" },
      failSlot, sendBtn,
      h("p", { class: "np-must", text: "보내기 버튼은 문자·메일 앱에서 직접 눌러요." }),
      copyBtn,
      h("a", { class: "btn ghost block np-sent-link", href: "#/alerts?tab=sent" }, icon("bell"), h("span", { text: "보낸 알림 보기" })));

    fill(main,
      h("p", { class: "page-sub", text: "걱정되는 거래를 조력자와 상담하는 곳에 알려요." }),
      step1, step2, step3, step4, sendArea);

    // 직접 고친 글이 있으면 떠나기 전에 묻는다
    const guard = () => confirmSheet({ title: "고친 글이 있어요", lines: ["나가면 고친 글이 사라져요."], confirmText: "나가기", cancelText: "계속 쓰기" });
    function setGuard() { ctx.session.unsaved = edited ? guard : (ctx.session.unsaved === guard ? null : ctx.session.unsaved); }
    ctx.onCleanup(() => { if (ctx.session.unsaved === guard) ctx.session.unsaved = null; });

    setMessage(autoMessage(picked));
    paintCounselorToggle();
    paint();

    // ---- 불러오기: 받는 사람(조력자·상담하는 곳)과 미리 고를 거래를 함께 ----
    const consentReady = ctx.req("GET", "/api/consent").then((c) => {
      ctx.session.consent = c;
      monitoring = Boolean(c && c.monitoring);
    }).catch(() => {});   // 못 읽으면 그대로 불러 보고, 오류는 그 자리에서 알린다
    await Promise.all([loadPeople(), loadPreset()]);

    async function loadPeople() {
      const [hp, co] = await Promise.allSettled([ctx.req("GET", "/api/helpers"), ctx.req("GET", "/api/counselors")]);
      if ([hp, co].some((r) => r.status === "rejected" && r.reason === STALE)) return;
      if (hp.status === "fulfilled") {
        const list = Array.isArray(hp.value) ? hp.value : (hp.value && hp.value.items) || [];
        helpers = list.map((x) => ({
          key: `helper:${x.id}`, kind: "helper", id: x.id, name: x.name, icon: "person",
          sub: [x.relation, x.phone_masked || x.email_masked || ""].filter(Boolean).join(" · "),
          phone: x.phone || "", email: x.email || "",
        }));
        // 돈 보내기에서 물어볼 사람을 골라 왔으면 그 사람만 체크해 둔다(추천이 덮어쓰지 않게, 추천 배지는 보인다)
        if (wantHelpers.size) for (const p of helpers) { touched.add(p.key); if (wantHelpers.has(String(p.id))) chosen.add(p.key); }
        applySuggestion(false);
        renderHelpers();
      } else {
        fill(helperSlot, retryBox(hp.reason, loadPeople));
      }
      if (co.status === "fulfilled") {
        counselors = ((co.value && co.value.items) || []).filter((x) => x.active !== false).map((x) => ({
          key: `counselor:${x.id}`, kind: "counselor", id: x.id, name: x.name, icon: COUNSELOR_KIND_ICON[x.kind] || "building",
          // 이름에 종류가 이미 있으면(장애인권익옹호기관 …) 종류를 또 쓰지 않는다
          sub: [String(x.name).includes(COUNSELOR_KIND_KO[x.kind] || "") ? "" : COUNSELOR_KIND_KO[x.kind], x.phone || x.email || ""].filter(Boolean).join(" · "),
          phone: x.phone || "", email: x.email || "",
        }));
        if (!helpers.length) counselorsOpen = true;   // 조력자가 없으면 상담하는 곳을 펼쳐 둔다
        if (wantHelpers.size) for (const p of counselors) touched.add(p.key);
        applySuggestion(false);
        renderCounselors();
      } else {
        counselorsOpen = true;
        fill(counselorSlot, retryBox(co.reason, loadPeople));
      }
      paintCounselorToggle();
      paint();
    }

    async function loadPreset() {
      await consentReady;
      if (!ctx.alive()) return;
      if (!monitoring) { renderPicked(); paint(); return; }   // 동의가 꺼져 있으면 추천도 받지 않는다
      try {
        if (wantIds.length) {
          picked = await findTxns(wantIds);
          if (picked.length < wantIds.length) toast("고른 거래 가운데 찾지 못한 것이 있어요.", "error");
        } else if (toCounselors) {
          // 상담 안내에서 왔으면 최근 꼭 확인할 거래를 미리 골라 둔다(빼도 된다)
          const d = await ctx.req("GET", "/api/transactions?level=high&limit=3");
          picked = d.items || [];
        }
      } catch (e) {
        if (e === STALE) return;
        picked = [];
        fill(pickedSlot, errorNotice(friendlyError(e), go));
        return;
      }
      if (!edited) setMessage(autoMessage(picked));
      renderPicked();
      paint();
      refreshSuggest();
    }

    // ---- 받는 사람 추천(POST /api/notify/suggest) ----
    async function refreshSuggest() {
      const seq = ++suggestSeq;
      let d;
      try {
        // 거래 이력에 적지 않은 확인 거래(돈 보내기의 물어볼래요)는 빼고 묻는다(서버가 모르는 거래)
        d = await ctx.req("POST", "/api/notify/suggest", { txn_ids: picked.filter((it) => !it.unsaved).map((it) => it.txn.id).slice(0, 20) });
      } catch (e) {
        if (e === STALE || seq !== suggestSeq) return;
        suggestion = null;   // 추천 없이 쓴다(체크는 그대로)
        renderHelpers();
        renderCounselors();
        paint();
        return;
      }
      if (seq !== suggestSeq || !ctx.alive()) return;
      const byId = (list) => new Map((Array.isArray(list) ? list : []).map((x) => [String(x.id), x]));
      suggestion = { helpers: byId(d && d.helpers), counselors: byId(d && d.counselors), due: Boolean(d && d.counseling_due) };
      applySuggestion(true);
    }

    function sugOf(p) {
      if (!suggestion) return null;
      return (p.kind === "helper" ? suggestion.helpers : suggestion.counselors).get(String(p.id)) || null;
    }
    const isConflict = (p) => Boolean(sugOf(p) && sugOf(p).conflict);

    /** 추천에 맞춰 체크한다: 본인이 바꾼 사람은 그대로, 돈을 받은 조력자는 체크를 푼다(fresh: 새 추천이 왔을 때). */
    function applySuggestion(fresh) {
      if (!suggestion) return;
      for (const p of [...helpers, ...counselors]) {
        const s = sugOf(p);
        if (s && s.conflict) { if (fresh || !touched.has(p.key)) chosen.delete(p.key); continue; }
        if (touched.has(p.key)) continue;
        if (s && s.suggested) chosen.add(p.key); else chosen.delete(p.key);
      }
      if (suggestion.due && counselors.some((p) => (sugOf(p) || {}).suggested)) counselorsOpen = true;
      if (!fresh) return;
      renderHelpers();
      renderCounselors();
      paint();
      const n = [...helpers, ...counselors].filter((p) => (sugOf(p) || {}).suggested && chosen.has(p.key)).length;
      if (n) announce(`추천하는 받는 사람 ${n}명을 미리 골랐어요.`);
    }

    /** 거래 id로 항목 찾기: 걱정되는 거래 → 최근 거래부터 500건씩. */
    async function findTxns(ids) {
      const found = new Map();
      // 돈 보내기에서 방금 확인한 거래(물어볼래요는 거래 이력에 적지 않는다)는 이 창이 기억한 항목을 쓴다
      for (const id of ids) if (checkedItem(id)) found.set(id, checkedItem(id));
      const want = new Set(ids);
      if (found.size >= want.size) return ids.map((id) => found.get(id)).filter(Boolean);
      const take = (items) => { for (const it of items || []) if (want.has(it.txn.id) && !found.has(it.txn.id)) found.set(it.txn.id, it); };
      take((await ctx.req("GET", "/api/transactions?level=caution&limit=200")).items);
      for (let offset = 0; found.size < want.size && offset < 20000; offset += 500) {
        const d = await ctx.req("GET", `/api/transactions?level=all&limit=500&offset=${offset}`);
        take(d.items);
        if (offset + 500 >= (d.matched ?? d.count ?? 0)) break;
      }
      return ids.map((id) => found.get(id)).filter(Boolean);
    }

    // ---- 그리기 ----
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

    function removePick(id) {
      picked = picked.filter((it) => it.txn.id !== id);
      ctx.replaceParams({ to: toCounselors ? "counselors" : null });   // 새로 고쳐도 뺀 거래가 다시 들어오지 않게
      if (!edited) setMessage(autoMessage(picked));
      renderPicked();
      paint();
      refreshSuggest();
      announce(picked.length ? `거래를 뺐어요. ${picked.length}건이 남았어요.` : "거래를 모두 뺐어요.");
      const first = pickedSlot.querySelector(".np-remove") || step1.querySelector("h3");
      if (first) first.focus();
    }

    function writeDirect() {
      picked = [];
      ctx.replaceParams({ to: toCounselors ? "counselors" : null });
      edited = false;
      setGuard();
      setMessage(autoMessage(picked));
      renderPicked();
      paint();
      refreshSuggest();
      msg.focus();
      msg.setSelectionRange(msg.value.length, msg.value.length);
      msg.scrollIntoView({ block: "center" });
    }

    function personRow(p) {
      const s = sugOf(p);
      const conflict = Boolean(s && s.conflict);
      const box = h("input", { type: "checkbox", checked: chosen.has(p.key) });
      const row = h("label", { class: `np-person${chosen.has(p.key) ? " on" : ""}${conflict ? " conflict" : ""}` },
        box,
        h("span", { class: "row-main" },
          h("span", { class: "row-title" }, icon(p.icon, "np-kind"), h("span", { text: p.name }),
            s && s.suggested && !conflict ? h("span", { class: "badge info np-rec" }, icon("check-line"), h("span", { text: "추천" })) : null),
          p.sub ? h("span", { class: "row-sub", text: p.sub }) : null,
          h("span", { class: "np-has-row" },
            hasTag("chat", p.phone ? "번호" : "번호 없음", Boolean(p.phone)),
            hasTag("mail", p.email ? "메일" : "메일 없음", Boolean(p.email))),
          conflict ? h("span", { class: "np-conflict" }, icon("warning"),
            h("span", null, splitSentences(CONFLICT_WARN).map((t) => h("span", { class: "sent", text: `${t} ` })))) : null));
      box.addEventListener("change", () => {
        touched.add(p.key);
        if (box.checked) chosen.add(p.key); else chosen.delete(p.key);
        row.classList.toggle("on", box.checked);
        paint();
      });
      return row;
    }

    function renderHelpers() {
      fill(helperSlot, helpers.length
        ? h("div", { class: "np-people", role: "group", "aria-label": "조력자" }, helpers.map(personRow))
        : h("div", { class: "np-none" },
          h("p", { text: "아직 정한 조력자가 없어요." }),
          h("button", { type: "button", class: "btn sm weak", onclick: () => go("more/helpers") }, icon("plus"), h("span", { text: "조력자 정하기" }))));
    }

    function renderCounselors() {
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

    function people() { return [...helpers, ...counselors].filter((p) => chosen.has(p.key)); }

    /** 이 방법을 쓸 수 있는지와 못 쓰는 이유. sel = 고른 받는 사람. */
    function channelState(value, sel) {
      if (value === "sms") {
        if (!caps.sms) return { ok: false, why: "문자는 휴대폰 앱에서 보낼 수 있어요." };
        if (sel.length && !sel.some((p) => p.phone)) return { ok: false, why: "고른 사람에게 휴대폰 번호가 없어요." };
        return { ok: true, to: sel.filter((p) => p.phone), lack: sel.filter((p) => !p.phone) };
      }
      if (value === "email") {
        if (!caps.email) return { ok: false, why: `${deviceWord()}에서는 메일 앱을 열 수 없어요.` };
        if (sel.length && !sel.some((p) => p.email)) return { ok: false, why: "고른 사람에게 메일 주소가 없어요." };
        return { ok: true, to: sel.filter((p) => p.email), lack: sel.filter((p) => !p.email) };
      }
      if (!caps.call) return { ok: false, why: "전화는 휴대폰 앱에서 걸 수 있어요." };
      if (sel.length !== 1 || sel[0].kind !== "counselor") return { ok: false, why: "전화는 상담하는 곳 한 곳만 골랐을 때 걸 수 있어요." };
      if (!sel[0].phone) return { ok: false, why: "고른 곳에 전화번호가 없어요." };
      return { ok: true, to: sel, lack: [] };
    }

    /** 고른 것에 맞춰 방법·이유·글 안내·보내기 버튼을 다시 그린다. */
    function paint() {
      const sel = people();
      const recs = suggestion ? [...helpers, ...counselors].filter((p) => (sugOf(p) || {}).suggested && !isConflict(p)) : [];
      recLine.hidden = !recs.length;
      if (recs.length) setText(recLine, "조력자 설정에 맞는 사람을 추천해요. 바꿔도 돼요.");
      const states = Object.fromEntries(CHANNELS.map((c) => [c.value, channelState(c.value, sel)]));
      // 고른 방법을 못 쓰게 되면 쓸 수 있는 첫 방법으로 옮긴다
      if (!states[channel].ok) {
        const next = CHANNELS.find((c) => states[c.value].ok);
        if (next) channel = next.value;
      }
      const ch = CHANNELS.find((c) => c.value === channel);
      for (const c of CHANNELS) {
        radios[c.value].disabled = !states[c.value].ok;
        radios[c.value].checked = c.value === channel;
      }
      fill(reasons, CHANNELS.filter((c) => !states[c.value].ok).map((c) =>
        h("li", { id: `np-why-${c.value}` }, icon("info"), h("span", { text: states[c.value].why }))));
      const st = states[channel];
      const lack = st.ok ? st.lack : [];
      missing.hidden = !lack.length;
      if (lack.length) {
        setText(missing, `${lack.map((p) => p.name).join(", ")}에게는 ${channel === "sms" ? "휴대폰 번호" : "메일 주소"}가 없어서 가지 않아요.`);
      }

      setText(step4.querySelector("h3"), channel === "call" ? "전화로 말할 내용" : "보낼 글");
      setText(msgHint, channel === "call"
        ? "전화 걸기 화면만 열어요. 전화는 직접 걸어요. 이 글을 보며 말하면 돼요."
        : channel === "email" ? `메일 제목은 ${picked.length ? SUBJECT : SUBJECT_DIRECT}이에요.` : "받는 사람이 읽기 쉽게 고쳐도 돼요.");
      msgCount.textContent = `${nf.format(msg.value.length)} / ${nf.format(MAX_MESSAGE)}자`;
      refill.hidden = !edited;

      sendIc.replaceChildren(icon(ch.icon));
      sendText.textContent = ch.open;
      const ready = sel.length > 0 && st.ok && msg.value.trim().length > 0;
      sendBtn.setAttribute("aria-disabled", ready ? "false" : "true");
      paintCounselorToggle();
    }

    // ---- 보내기: 앱 열기 → 기록 → 알림 탭 ----
    async function send() {
      const sel = people();
      const st = channelState(channel, sel);
      const message = msg.value.trim();
      if (!sel.length) { toast("알릴 사람을 골라 주세요.", "error"); step2.querySelector("h3").focus(); step2.scrollIntoView({ block: "start" }); return; }
      if (!st.ok) { toast(st.why, "error"); step3.querySelector("h3").focus(); return; }
      if (!message) { toast("보낼 글을 적어 주세요.", "error"); msg.focus(); return; }
      if (sendBtn.getAttribute("aria-busy") === "true") return;
      const risky = sel.filter(isConflict);
      if (risky.length) {
        const ok = await confirmSheet({
          title: "돈을 받은 사람에게도 알릴까요?",
          lines: [`${risky.map((p) => p.name).join(", ")}: ${splitSentences(CONFLICT_WARN)[0]}`, ...splitSentences(CONFLICT_WARN).slice(1)],
          confirmText: "그래도 보낼래요", cancelText: "다시 고를래요",
        });
        if (!ok) { step2.querySelector("h3").focus(); return; }
      }
      const ch = CHANNELS.find((c) => c.value === channel);
      const to = st.to.slice(0, MAX_TO);
      const uri = channel === "sms" ? smsUri(to.map((p) => p.phone), message)
        : channel === "email" ? mailtoUri(to.map((p) => p.email), picked.length ? SUBJECT : SUBJECT_DIRECT, message)
          : telUri(to[0].phone);
      failSlot.replaceChildren();
      if (!openExternal(uri)) {
        fill(failSlot, h("div", { class: "notice red" }, icon("warning"), h("div", null,
          h("p", { text: `${deviceWord()}에서 ${ch.app}을 열지 못했어요. 글을 복사해서 직접 보내 주세요.` }),
          h("button", { type: "button", class: "btn sm weak notice-action", onclick: (e) => copyMessage(e.currentTarget) }, icon("copy"), h("span", { text: "글 복사하기" })))));
        failSlot.scrollIntoView({ block: "center" });
        return;
      }
      sendBtn.setAttribute("aria-busy", "true");
      const ok = await record(channel, to, message);
      if (!sendBtn.isConnected) return;
      sendBtn.removeAttribute("aria-busy");
      if (!ok) return;
      edited = false;
      setGuard();
      toast(`${ch.app}을 열었어요. 보낸 알림에 적어 두었어요.`);
      go("alerts?tab=sent");
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

    async function copyMessage(btn) {
      const message = msg.value.trim();
      if (!message) { toast("보낼 글을 적어 주세요.", "error"); msg.focus(); return; }
      if (btn && btn.getAttribute("aria-busy") === "true") return;
      const ok = await copyText(message);
      if (!ok) {
        // 직접 복사하기 쉽게 보낼 글을 모두 골라 둔다
        msg.focus();
        msg.select();
        msg.scrollIntoView({ block: "center" });
        toast("글을 복사하지 못했어요. 골라 둔 글을 길게 눌러 복사해 주세요.", "error");
        return;
      }
      toast("글을 복사했어요. 문자나 메일에 붙여 넣어 주세요.");
      const sel = people();
      if (sel.length && lastCopied !== message) {   // 같은 글은 한 번만 기록한다
        if (btn) btn.setAttribute("aria-busy", "true");
        if (await record("copy", sel, message)) lastCopied = message;
        if (btn && btn.isConnected) btn.removeAttribute("aria-busy");
      }
    }

    // ---- 거래 고르기 시트: 꼭 확인할 거래 · 걱정되는 거래 · 담은 거래(칩으로 고르는 보기) ----
    function openPicker() {
      let draft = picked.slice();
      const data = {};
      let view = "high";
      const panel = h("div", { class: "np-pick-panel" }, skeleton(2));
      const doneText = h("span");
      const done = h("button", { type: "button", class: "btn primary big block" }, doneText);
      const chipBtns = PICK_TABS.map((t) => h("button", {
        type: "button", class: "chip", "data-v": t.value, "aria-pressed": "false",
        onclick: () => { view = t.value; paintChips(); show(); const line = panel.querySelector(".np-pick-total"); if (line) announce(line.textContent); },
      }, h("span", { text: t.label })));
      const chips = h("div", { class: "chips np-pick-chips", role: "group", "aria-label": "거래 보기" }, chipBtns);

      function paintChips() { for (const b of chipBtns) b.setAttribute("aria-pressed", b.dataset.v === view ? "true" : "false"); }
      function paintDone() { doneText.textContent = draft.length ? `${nf.format(draft.length)}건 고르기` : "고르지 않기"; }

      function show() {
        const t = PICK_TABS.find((x) => x.value === view);
        const d = data[view];
        if (!d) { fill(panel, skeleton(2)); return; }
        if (d.error) { fill(panel, errorNotice(friendlyError(d.error), go)); return; }
        if (!d.items.length) {
          fill(panel, h("div", { class: "empty" }, icon(view === "flags" ? "bookmark" : "check-line"),
            h("b", { text: view === "flags" ? "담은 거래가 없어요" : `${t.label}가 없어요` }),
            h("p", { text: view === "flags" ? "내 거래에서 거래를 누르면 알림 목록에 담을 수 있어요." : "다른 보기를 골라 보세요." })));
          return;
        }
        fill(panel, h("p", { class: "np-pick-total", text: d.total > d.items.length
          ? `${t.label} ${nf.format(d.total)}건 가운데 최근 ${nf.format(d.items.length)}건이에요.`
          : `${t.label} ${nf.format(d.total)}건이에요.` }),
        h("div", { class: "np-pick-list", role: "group", "aria-label": t.label }, d.items.map((it) => {
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
        })));
      }

      const sheet = openSheet((close) => {
        done.addEventListener("click", () => {
          picked = draft.slice(0, MAX_PICK);
          ctx.replaceParams({ to: toCounselors ? "counselors" : null });
          if (!edited) setMessage(autoMessage(picked));
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
          h("div", { class: "sheet-actions" }, done,
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
        ctx.req("GET", t.path).then((d) => {
          const items = t.value === "flags" ? (d.items || []).map((x) => x.item).filter(Boolean) : (d.items || []);
          data[t.value] = { items, total: t.value === "flags" ? items.length : (d.matched ?? items.length) };
          // 꼭 확인할 거래가 없으면 걱정되는 거래부터 보인다
          if (t.value === "high" && !items.length && view === "high") { view = "caution"; paintChips(); }
          if (sheet.el.isConnected) show();
        }).catch((e) => {
          if (e === STALE) return;
          data[t.value] = { error: e, items: [] };
          if (sheet.el.isConnected) show();
        });
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
    item.flagged ? flaggedBadge() : null, item.practice ? checkedBadge() : null].filter(Boolean);
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
