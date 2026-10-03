/* 알림: 걱정되는 거래(쉬운 말 카드) · 담은 거래 · 보낸 알림. 카드·담은 거래마다 알리기(→ 알림 보내기).
 * - 탭은 주소 뒤 tab 값(cards|flags|sent)으로 고른다. 옛 이름 risky·flagged도 받는다.
 * - 상담 안내 띠: 상담하는 곳에 알려 주기 동의 + 꼭 확인할 거래가 30일 동안 기준 이상이면 → 알림 보내기(상담하는 곳).
 * - 걱정되는 거래 카드
 *   [알리기]·[알림 목록에 담기]·[내가 한 거예요]·[자세히]. 담기 글은 FLAG_TEXT, 내가 한 거예요 글은 REVIEW_TEXT(공용 버튼).
 *   걱정되는 거래 수는 내가 한 거예요로 표시한 것을 빼고 세고, 뺀 건수를 함께 보인다(탐지 등급은 그대로, 수정 계획 1-C).
 *   같은 신호·같은 상대(휴대폰 결제·요금은 같은 방법)가 7일 안에 이어지면 같은 일 N건으로 묶고 펼칠 수 있다(J5).
 *   [자세히]는 거래 시트를 연다: 왜 걱정되나요(약속(규칙) + AI가 본 것) + 지금 할 수 있는 일(J8·J6).
 *   30건씩 더 불러온다(FN-05).
 * - 보낸 알림: 문자·메일 앱을 열어 직접 보낸 기록(다시 보내기·지우기, AUG-06)과, 조력자 설정대로 적어 두기만 한 기록
 *   (보낸 것이 아님, 적어 둔 기록으로 따로 보이고 알림 보내기로 직접 보내는 길을 둔다, 수정 계획 1-A)을 나눈다. 100건씩 더 본다(FN-04).
 * - 소리로 듣기는 탭을 바꾸거나 목록을 다시 그리면 저절로 멈춘다(components.speakButton).
 */
import { h, icon, fill, setText, toast, announce, skeleton, segTabs, openSheet, confirmSheet } from "../ui.js";
import { nf, formatTime, parseTs, deviceWord, moneyText } from "../format.js";
import { alertCard, txnAmount, txnSignals, levelBadge, flagBadge, reviewBadge, notifiedBadge, errorNotice, subParts, whenParts,
  flagButton, reviewButton, aiExplain, txnDetailHead } from "../components.js";
import { LEVEL, CHANNEL_KO, CHANNEL_ICON, NOTICE_CHANNEL_KO, NOTICE_CHANNEL_ICON, FLAG_TEXT } from "../labels.js";
import { STALE } from "../api.js";

const TABS = [
  { value: "cards", label: "걱정되는 거래" },
  { value: "flags", label: FLAG_TEXT.list },
  { value: "sent", label: "보낸 알림" },
];
const ALIAS = { risky: "cards", flagged: "flags" };
const MAX_SEND = 5;            // 알림 보내기에서 한 번에 고를 수 있는 거래 수(notify.js와 같음)
const COUNSEL_DAYS = 30;       // 상담 안내 기준 기간(api settings.window_long_days)
const COUNSEL_MIN = 3;         // 상담 안내 기준 건수(api settings.high_repeat_for_counseling)
const LONG_MESSAGE = 90;       // 이보다 긴 글은 접어 두고 글 모두 보기
const CARD_PAGE = 30;          // 걱정되는 거래 카드를 한 번에 불러오는 수
const CARD_MAX = 500;          // api CardsQuery.limit 한도
const SENT_PAGE = 100;         // 보낸 알림을 한 번에 보이는 수
const SAME_DAYS = 7;           // 같은 일로 묶는 기간
// 상대 대신 결제 방법으로 묶는 신호(가맹점·회선 이름이 거래마다 달라도 같은 일이다)
const GROUP_BY_CHANNEL = new Set(["micropay_surge", "multi_line_telecom"]);
// 지금 할 수 있는 일(J6). 기관 이름·전화번호·서비스 이름은 쓰지 않는다(1차 출처로 확인한 것만 쓴다는 원칙).
// 번호가 필요한 곳은 내가 정한 상담하는 곳 목록(알림 보내기)으로 잇는다
const NEXT_STEPS = {
  night_repeat_transfer: ["누가 시켜서 보낸 돈이면 더 보내지 말고 조력자나 상담하는 곳에 알려요.", "이미 보낸 돈이 걱정되면 내 은행 고객센터에 바로 물어봐요."],
  payee_surge: ["같은 사람이 계속 돈을 달라고 하면 보내기 전에 조력자에게 물어봐요.", "이미 보낸 돈이 걱정되면 내 은행 고객센터에 바로 물어봐요."],
  micropay_surge: ["누가 결제해 달라고 했다면 더 결제하지 말고 조력자에게 알려요.", "휴대폰 결제를 막는 방법은 내 통신사 고객센터에 물어봐요."],
  new_merchant_high_value: ["내가 산 것이 아니면 결제한 카드나 은행의 고객센터에 바로 알려요.", "누가 사 달라고 했다면 조력자에게 알려요."],
  multi_line_telecom: ["내가 만들지 않은 휴대폰이면 그 통신사 고객센터에 내 이름으로 된 휴대폰을 물어봐요.", "누가 내 이름으로 휴대폰을 만들었다면 상담하는 곳에 알려요."],
  anomaly: ["내가 한 거래가 아니면 조력자에게 물어봐요.", "내가 한 거래가 맞으면 내가 한 거예요 버튼을 눌러요."],
};

/** #/send?txn=a&txn=b */
function sendHref(ids) {
  return "#/send?" + ids.map((id) => "txn=" + encodeURIComponent(id)).join("&");
}

/** 404인데 쉬운 말 안내가 없으면(새 기능을 아직 못 쓰는 엔진) 쉬운 말로 바꾼다. */
function friendlyError(e) {
  if (e && e.status === 404 && !/[가-힣]/.test(String(e.message || ""))) {
    return Object.assign(new Error("이 기능을 아직 쓸 수 없어요. 잠시 뒤 다시 해 주세요."), { status: 404 });
  }
  return e;
}

/** "6월 27일" */
function dayText(d) { return d ? `${d.getMonth() + 1}월 ${d.getDate()}일` : ""; }

export default {
  title: "알림",
  tab: "alerts",
  async render(ctx) {
    const { main, go } = ctx;
    let tab = ctx.params.get("tab") || "cards";
    tab = ALIAS[tab] || tab;
    if (!TABS.some((t) => t.value === tab)) tab = "cards";
    if (ctx.params.get("tab") !== tab) ctx.replaceParams({ tab });

    const cache = {};    // 탭 이름 → 응답 Promise(바뀐 쪽만 지운다)
    let cardLimit = CARD_PAGE;
    let sentShown = SENT_PAGE;
    const PATHS = { cards: () => `/api/cards?limit=${cardLimit}`, flags: () => "/api/flags", sent: () => "/api/notices" };
    let seq = 0;
    let bandDone = false;
    let monitoring = true;   // 거래 살펴보기 동의(꺼져 있으면 걱정되는 거래·담은 거래를 부르지 않는다)
    let focusCard = -1;      // 더 보기 뒤 초점을 줄 카드 번호
    const cardOpts = { question: true };   // 카드 질문 줄(목록 공통이면 목록 위에 한 번만)

    const band = h("div", { class: "al-band-slot" });
    const panel = h("div", { class: "al-panel", id: "alerts-panel", role: "tabpanel", tabindex: "-1" });
    // 건수는 불러온 뒤 채운다(빈 칸 자리를 미리 둬서 글자가 밀리지 않게)
    const tabs = segTabs(TABS.map((t) => ({ ...t, count: "" })), tab, (v) => { tab = v; ctx.replaceParams({ tab: v }); show(); },
      { label: "알림 보기", controls: "alerts-panel" });
    tabs.el.classList.add("al-tabs");
    // 좁은 화면에서 세 칸 이름이 모두 낱말 사이에서 두 줄이 되게 줄바꿈 자리를 넣는다(넓으면 CSS가 한 줄로 보임, D8)
    for (const s of tabs.el.querySelectorAll(".seg-tab > span:first-child")) s.textContent = s.textContent.replace(" ", "\n");

    fill(main,
      h("h2", { class: "page-title", tabindex: "-1", text: "알림" }),
      h("p", { class: "page-sub", text: "걱정되는 거래를 모아 보고, 조력자와 상담하는 곳에 알려요." }),
      band, h("div", { class: "al-tabs-wrap" }, tabs.el), panel);

    function get(name, force = false) {
      if (!monitoring && name !== "sent") return Promise.resolve({ consentOff: true });
      if (force || !cache[name]) {
        const p = ctx.req("GET", PATHS[name]());
        cache[name] = p;
        p.then((d) => { if (cache[name] === p) countOf(name, d); }).catch(() => { if (cache[name] === p) delete cache[name]; });
      }
      return cache[name];
    }

    function countOf(name, d) {
      if (d.consentOff) return;
      const n = name === "cards" ? (d.open ?? d.total ?? (d.items || []).length)
        : name === "sent" ? (d.items || []).filter((x) => x.kind === "manual").length
          : (d.items || []).length;
      setTabCount(tabs.el, name, n);
      if (name === "cards" && !bandDone) { bandDone = true; renderBand(d.counseling); }
    }

    async function show(force = false) {
      const my = ++seq;
      const t = TABS.find((x) => x.value === tab);
      panel.setAttribute("aria-label", t.label);
      fill(panel, skeleton(2));
      try {
        const d = await get(tab, force);
        if (my !== seq) return;
        if (d.consentOff) showConsentOff();
        else if (tab === "cards") showCards(d);
        else if (tab === "flags") showFlags(d);
        else showSent(d);
      } catch (e) {
        if (e === STALE || my !== seq) return;
        fill(panel, errorNotice(friendlyError(e), go),
          h("button", { type: "button", class: "btn sm weak", onclick: () => show(true) }, icon("refresh"), h("span", { text: "다시 불러오기" })));
      }
    }

    function showConsentOff() {
      fill(panel, h("div", { class: "empty" }, icon("toggle"),
        h("b", { text: "거래 살펴보기가 꺼져 있어요" }),
        h("p", { text: tab === "flags" ? "거래 살펴보기를 켜면 담은 거래를 볼 수 있어요." : "거래 살펴보기를 켜면 걱정되는 거래를 쉬운 말로 알려 줘요." }),
        h("button", { type: "button", class: "btn weak", onclick: () => go("more/consent") }, icon("toggle"), h("span", { text: "동의 켜러 가기" }))));
    }

    // ================= 걱정되는 거래: 쉬운 말 카드 =================
    function showCards(d) {
      const items = d.items || [];
      if (!items.length) {
        fill(panel, h("div", { class: "empty" }, icon("check-line"),
          h("b", { text: "걱정되는 거래가 없어요" }),
          h("p", { text: "걱정되는 거래가 생기면 여기에 쉬운 말로 알려 줘요." }),
          h("button", { type: "button", class: "btn weak", onclick: () => go("txns") }, icon("list"), h("span", { text: "내 거래 보기" }))));
        return;
      }
      const total = d.total ?? items.length;
      const stats = { open: d.open ?? total, reviewed: d.reviewed ?? 0 };
      // 모든 카드의 질문 줄이 같으면(지난 거래: 그때 걱정했던 거래예요.) 카드마다 쓰지 않고 목록 위에 한 번만 쓴다(⑥)
      const q0 = (items[0].card && items[0].card.question) || "";
      const common = items.length > 1 && q0 && items.every((it) => it.card && it.card.question === q0) ? q0 : "";
      const summary = h("div", { class: "al-summary", "aria-live": "polite" });
      function paintSummary() {
        // 건수와 보여 주는 범위(+ 카드 공통 문장)는 한 문단, 내가 확인해서 뺀 건수는 표시와 함께 따로
        fill(summary,
          h("p", { text: [stats.open > 0 ? `걱정되는 거래가 ${nf.format(stats.open)}건 있어요.` : "걱정되는 거래를 모두 내가 확인했어요.",
            total > items.length ? `최근 ${nf.format(items.length)}건을 보여 드려요.` : "",
            common ? common.replace(/^그때 /, "모두 그때 ") : ""].filter(Boolean).join(" ") }),
          stats.reviewed > 0 ? h("p", { class: "al-reviewed-note" }, icon("user-check"), h("span", { text: `내가 확인한 ${nf.format(stats.reviewed)}건은 뺐어요.` })) : null);
        setTabCount(tabs.el, "cards", stats.open);
      }
      const onReviewed = (on) => {
        stats.open = Math.max(0, stats.open + (on ? -1 : 1));
        stats.reviewed = Math.max(0, stats.reviewed + (on ? 1 : -1));
        paintSummary();
        delete cache.flags;   // 담은 거래 줄의 내가 확인함 표시
        cache.cards = Promise.resolve({ ...d, open: stats.open, reviewed: stats.reviewed });
      };
      paintSummary();
      const groups = groupCards(items);
      cardOpts.question = !common;
      const cardsEl = h("div", { class: "al-cards" }, groups.map((g) => renderGroup(g, onReviewed)));
      const left = total - items.length;
      fill(panel, summary, cardsEl,
        left > 0 && cardLimit < CARD_MAX ? h("button", { type: "button", class: "btn weak block al-more", onclick: () => {
          focusCard = items.length;
          cardLimit = Math.min(CARD_MAX, cardLimit + CARD_PAGE);
          delete cache.cards;
          show();
        } }, icon("chevron-down"), h("span", { text: `${nf.format(Math.min(CARD_PAGE, left))}건 더 보기` })) : null,
        left > 0 && cardLimit >= CARD_MAX ? h("div", { class: "al-more-note" },
          h("p", { text: "더 오래된 거래는 내 거래에서 볼 수 있어요." }),
          h("button", { type: "button", class: "btn sm weak", onclick: () => go("txns") }, icon("list"), h("span", { text: "내 거래 보기" }))) : null);
      if (focusCard >= 0) {
        const n = focusCard;
        focusCard = -1;
        // 묶음 때문에 화면 순서와 목록 순서가 다를 수 있어 거래 id로 찾는다
        const id = items[n] ? String(items[n].txn.id) : "";
        const target = id ? panel.querySelector(`.alert-card[data-txn="${CSS.escape(id)}"]`) : null;
        if (target) {
          const rest = target.closest(".al-group-rest");
          if (rest && rest.hidden) rest.previousElementSibling?.click();
          target.setAttribute("tabindex", "-1");
          target.focus();
        } else {
          panel.focus({ preventScroll: true });
        }
        announce(`카드를 더 불러왔어요. 모두 ${nf.format(items.length)}건이에요.`);
      }
    }

    /**
     * 같은 일 묶기(J5): 목록 전체에서 같은 신호·같은 상대(휴대폰 결제·요금은 같은 방법)이고 7일 안에 든 카드를 한 묶음으로.
     * 사이에 다른 카드가 끼어 있어도 묶는다(이웃한 카드끼리만 보면 같은 일이 갈라져 보인다). 묶음 안 거래가 모두 7일 안에
     * 들 때만 더한다(사슬처럼 길게 늘어나지 않게). 묶음은 첫 카드가 있던 자리에 두고, 안은 최근 거래부터 보인다.
     */
    function groupCards(items) {
      const keyOf = (it) => {
        const sig = (it.signals || [])[0] || "anomaly";
        const who = GROUP_BY_CHANNEL.has(sig) ? it.txn.channel : (it.txn.counterparty || it.txn.channel);
        return `${sig}|${who}`;
      };
      const span = SAME_DAYS * 86400000;
      const out = [];
      for (const it of items) {
        const key = keyOf(it);
        const d = parseTs(it.txn.ts);
        const t = d ? d.getTime() : NaN;
        const g = Number.isFinite(t) ? out.find((x) => x.key === key && x.oldest && x.newest
          && Math.max(x.newest.getTime(), t) - Math.min(x.oldest.getTime(), t) <= span) : null;
        if (g) {
          g.items.push(it);
          if (t < g.oldest.getTime()) g.oldest = d;
          if (t > g.newest.getTime()) g.newest = d;
        } else {
          out.push({ key, items: [it], newest: d, oldest: d });
        }
      }
      const time = (it) => { const d = parseTs(it.txn.ts); return d ? d.getTime() : 0; };
      for (const g of out) g.items.sort((a, b) => time(b) - time(a));
      return out;
    }

    function renderGroup(g, onReviewed) {
      if (g.items.length === 1) return cardEl(g.items[0], onReviewed);
      const [first, ...rest] = g.items;
      const id = `al-group-${String(first.txn.id).replace(/[^\w-]/g, "")}`;
      const restBox = h("div", { class: "al-group-rest", id, hidden: true }, rest.map((it) => cardEl(it, onReviewed)));
      const sum = g.items.reduce((a, it) => a + (Number(it.txn.amount) || 0), 0);
      const range = dayText(g.oldest) === dayText(g.newest) ? dayText(g.newest) : `${dayText(g.oldest)} ~ ${dayText(g.newest)}`;   // 물결 앞뒤 빈칸: 좁은 칸에서 날짜 사이(빈칸)에서만 줄을 바꾼다
      const toggleText = h("span", { text: `같은 일 ${nf.format(rest.length)}건 더 보기` });
      const toggle = h("button", { type: "button", class: "btn weak block al-group-toggle", "aria-expanded": "false", "aria-controls": id },
        icon("chevron-down", "al-group-chev"), toggleText);
      toggle.addEventListener("click", () => {
        const open = restBox.hidden;
        restBox.hidden = !open;
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
        toggleText.textContent = open ? "같은 일 접기" : `같은 일 ${nf.format(rest.length)}건 더 보기`;
      });
      return h("section", { class: "al-group", "aria-label": `같은 일 ${nf.format(g.items.length)}건` },
        h("div", { class: "al-group-head" }, icon("list"),
          h("div", { class: "al-group-main" },
            h("b", { text: `같은 일 ${nf.format(g.items.length)}건` }),
            // 카드 줄의 7일 동안 모두(약속 기준 합계)와 헷갈리지 않게, 이 묶음 카드의 금액을 더한 값이라고 쓴다
            subParts([range, `더하면 ${moneyText(sum)}`], "row-sub al-group-sub"))),
        cardEl(first, onReviewed), toggle, restBox);
    }

    /** 카드 한 장: [알리기]·[알림 목록에 담기]·[내가 한 거예요]·[자세히]. 바꾸면 머리 배지를 다시 그린다. */
    function cardEl(item, onReviewed) {
      item.level = item.level || (item.card && item.card.level);
      const ref = { el: null };
      const who = item.txn.counterparty || "이름 없음";
      const card = alertCard(item, { question: cardOpts.question, actions: [
        h("a", { class: "btn sm weak al-send", href: `#/send?txn=${encodeURIComponent(item.txn.id)}`, "aria-label": `${who} 거래 알리기` }, icon("send"), h("span", { text: "알리기" })),
        h("button", { type: "button", class: "btn sm weak al-detail-btn", "aria-label": `${who} 거래 자세히`, onclick: () => openDetail(item, ref, onReviewed) },
          icon("info"), h("span", { text: "자세히" })),
        flagButton(ctx, item, { cls: "btn sm al-flag-btn", onChange: (on, count) => {
          repaintBadges(ref.el, item);
          delete cache.flags;   // 담은 거래 탭은 다음에 새로 불러온다
          if (Number.isInteger(count)) setTabCount(tabs.el, "flags", count);
        } }),
        reviewButton(ctx, item, { cls: "btn sm al-review-btn", onChange: (on) => { repaintBadges(ref.el, item); onReviewed(on); } }),
      ] });
      card.classList.toggle("reviewed", Boolean(item.reviewed));
      card.dataset.txn = String(item.txn.id);
      ref.el = card;
      return card;
    }

    /** 카드 머리의 담음·내가 확인함·알렸어요 배지를 지금 상태로 다시 그린다(등급 배지는 그대로). */
    function repaintBadges(cardNode, item) {
      if (!cardNode) return;
      const head = cardNode.querySelector(".alert-head");
      if (head) {
        head.querySelectorAll(".badge.info, .badge.ok-line, .badge.grey").forEach((b) => b.remove());
        for (const b of [flagBadge(item), reviewBadge(item), notifiedBadge(item)]) if (b) head.append(b);
      }
      cardNode.classList.toggle("reviewed", Boolean(item.reviewed));
    }

    /** 카드 → 거래 자세히(J8): 왜 걱정되나요(약속(규칙) + AI가 본 것) + 지금 할 수 있는 일(J6) + 담기·내가 한 거예요·알리기. */
    function openDetail(item, ref, onReviewed) {
      const t = item.txn;
      let changed = false;
      const badges = h("span", { class: "tx-badges" });
      const paintHead = () => fill(badges, levelBadge(item.level), flagBadge(item), reviewBadge(item), notifiedBadge(item));
      paintHead();
      const steps = nextSteps(item);
      // 내 거래 시트와 같은 머리(이름·배지 → 금액 → 사실 상자, ⑭)
      openSheet((close) => [
        txnDetailHead(item, badges),
        aiExplain(item, { heading: 3 }),
        h("section", { class: "sheet-section al-next", "aria-labelledby": "al-next-title" },
          h("h3", { class: "al-next-title", id: "al-next-title", text: "지금 할 수 있는 일" }),
          h("ul", { class: "al-next-list" }, steps.map((s) => h("li", null, icon("check-line"), h("p", { text: s })))),
          h("div", { class: "btn-row al-next-btns" },
            h("button", { type: "button", class: "btn weak", onclick: () => { close(); go(`send?txn=${encodeURIComponent(t.id)}`); } },
              icon("users"), h("span", { text: "조력자에게 알리기" })),
            h("button", { type: "button", class: "btn weak", onclick: () => { close(); go(`send?to=counselors&txn=${encodeURIComponent(t.id)}`); } },
              icon("building"), h("span", { text: "상담하는 곳에 알리기" })))),
        h("div", { class: "sheet-actions" },
          flagButton(ctx, item, { onChange: (on, count) => {
            changed = true;
            paintHead();
            delete cache.flags;
            if (Number.isInteger(count)) setTabCount(tabs.el, "flags", count);
          } }),
          reviewButton(ctx, item, { cls: "btn weak big block", onChange: (on) => { changed = true; paintHead(); onReviewed(on); } }),
          h("button", { type: "button", class: "btn big block", text: "닫기", onclick: () => close() })),
      ], {
        label: "거래 자세히",
        className: "tx-sheet",
        onClose: () => {
          if (!changed || !ref.el || !ref.el.isConnected || !ctx.alive()) return;
          // 카드의 담기·내가 한 거예요 버튼도 바뀐 상태로 다시 만든다(초점은 새 카드의 자세히로)
          const fresh = cardEl(item, onReviewed);
          ref.el.replaceWith(fresh);
          ref.el = fresh;
          window.requestAnimationFrame(() => { const b = fresh.querySelector(".al-detail-btn"); if (b && b.isConnected) b.focus(); });
        },
      });
    }

    // ================= 담은 거래: 알리기 · 빼기 =================
    function showFlags(d) {
      const items = (d.items || []).filter((x) => x && x.item);
      if (!items.length) {
        fill(panel, h("div", { class: "empty" }, icon("bookmark"),
          h("b", { text: "담은 거래가 없어요" }),
          h("p", { text: "내 거래에서 거래를 누르면 알림 목록에 담을 수 있어요." }),
          h("button", { type: "button", class: "btn weak", onclick: () => go("txns") }, icon("list"), h("span", { text: "내 거래 보기" }))));
        return;
      }
      const head = h("p", { class: "al-summary" });
      const sendAllText = h("span");   // 버튼 이름(ui.h가 그림과 함께 span.btn-label로 묶으므로 이 span을 직접 고친다)
      const sendAll = h("a", { class: "btn primary block al-send-all", href: "#/send" }, icon("send"), sendAllText);
      const list = h("ul", { class: "list al-flags", "aria-label": FLAG_TEXT.list });
      function paintHead() {
        const n = list.children.length;
        setText(head, `${FLAG_TEXT.list}가 ${nf.format(n)}건 있어요.`);
        // 한 번에 알릴 5건은 담은 순서가 아니라 거래가 일어난 때가 최근인 것부터 고른다(RF-9)
        const left = Array.from(list.children).map((li) => ({ id: li.dataset.id, ts: li.dataset.ts || "" }))
          .sort((a, b) => (a.ts < b.ts ? 1 : a.ts > b.ts ? -1 : 0)).slice(0, MAX_SEND).map((x) => x.id);
        sendAll.setAttribute("href", sendHref(left));
        setText(sendAllText, n > MAX_SEND ? `최근 거래 ${MAX_SEND}건 한 번에 알리기` : `${FLAG_TEXT.list} 한 번에 알리기`);
        setTabCount(tabs.el, "flags", n);
        if (!n) showFlags({ items: [] });
      }
      for (const x of items) {
        const item = x.item;
        const id = item.txn.id;
        const li = h("li", { class: "al-flag", "data-id": id, "data-ts": String(item.txn.ts || "") });
        const out = h("button", { type: "button", class: "btn sm al-out", "aria-label": `${item.txn.counterparty || "이름 없음"} 거래 빼기`, onclick: async () => {
          if (out.getAttribute("aria-busy") === "true") return;
          out.setAttribute("aria-busy", "true");
          out.setAttribute("aria-disabled", "true");
          try {
            await ctx.req("POST", "/api/flags/remove", { txn_id: id });
            const next = li.nextElementSibling || li.previousElementSibling;
            li.remove();
            delete cache.cards;   // 카드의 담음 표시가 바뀌었다
            cache.flags = Promise.resolve({ items: items.filter((y) => list.querySelector(`[data-id="${CSS.escape(y.item.txn.id)}"]`)) });
            paintHead();
            toast(FLAG_TEXT.removed);
            const focusTo = next && next.isConnected ? next.querySelector(".al-out") : panel;
            if (focusTo) focusTo.focus();
          } catch (e) {
            if (e !== STALE) toast(friendlyError(e).message || "빼지 못했어요. 다시 해 주세요.", "error");
          } finally {
            if (out.isConnected) { out.removeAttribute("aria-busy"); out.removeAttribute("aria-disabled"); }
          }
        } }, icon("minus"), h("span", { text: "빼기" }));
        li.append(datedTxn(item),
          h("div", { class: "al-row-actions" },
            h("a", { class: "btn sm weak", href: sendHref([id]), "aria-label": `${item.txn.counterparty || "이름 없음"} 거래 알리기` }, icon("send"), h("span", { text: "알리기" })),
            out));
        list.append(li);
      }
      fill(panel, head, sendAll, list);
      paintHead();
    }

    // ================= 보낸 알림: 직접 보낸 기록 + 적어 둔 기록 =================
    function showSent(d) {
      const all = d.items || [];
      const manual = all.filter((x) => x.kind === "manual");
      const auto = all.filter((x) => x.kind !== "manual");
      const note = d.delivery_note ? String(d.delivery_note).replace(/^이 기기/, deviceWord()) : "";
      setTabCount(tabs.el, "sent", manual.length);
      if (!all.length) {
        fill(panel, h("div", { class: "empty" }, icon("send"),
          h("b", { text: "아직 보낸 알림이 없어요" }),
          h("p", { text: "알림 보내기에서 조력자와 상담하는 곳에 알릴 수 있어요." }),
          h("button", { type: "button", class: "btn weak", onclick: () => go("send?mode=notify") }, icon("send"), h("span", { text: "알림 보내기" }))));
        return;
      }
      const sentList = h("ul", { class: "list al-sent", "aria-label": "보낸 알림" });
      const summary = h("p", { class: "al-summary" });
      const moreSlot = h("div");
      function paintManual() {
        const rest = manual.filter((n) => !n.__gone);
        setText(summary, rest.length ? `보낸 알림 ${nf.format(rest.length)}건이에요.` : "직접 보낸 알림은 아직 없어요.");
        setTabCount(tabs.el, "sent", rest.length);
        const shown = Math.min(sentShown, rest.length);
        const have = sentList.children.length;
        for (const n of rest.slice(have, shown)) sentList.append(sentRow(n, paintManual));
        const left = rest.length - sentList.children.length;
        fill(moreSlot, left > 0 ? h("button", { type: "button", class: "btn weak block al-more", onclick: () => {
          const from = sentList.children.length;
          sentShown += SENT_PAGE;
          paintManual();
          const first = sentList.children[from];
          if (first) { first.setAttribute("tabindex", "-1"); first.focus(); }
          announce(`보낸 알림을 더 보여 드려요. ${nf.format(sentList.children.length)}건이에요.`);
        } }, icon("chevron-down"), h("span", { text: `${nf.format(Math.min(SENT_PAGE, left))}건 더 보기` })) : null);
      }
      const autoSection = auto.length ? h("section", { class: "al-auto", "aria-labelledby": "al-auto-title" },
        h("h3", { class: "al-auto-title", id: "al-auto-title" }, icon("edit"), h("span", { text: `적어 둔 기록 ${nf.format(auto.length)}건` })),
        h("div", { class: "notice orange" }, icon("info"), h("p", { text: `조력자 설정대로 ${deviceWord()}에 적어 두기만 한 기록이에요. 아직 아무에게도 보내지 않았어요. 알리려면 알림 보내기로 직접 보내 주세요.` })),
        h("ul", { class: "list al-sent al-auto-list", "aria-label": "적어 둔 기록" }, auto.slice(0, SENT_PAGE).map(autoRow))) : null;
      fill(panel,
        note && manual.length ? h("div", { class: "notice" }, icon("info"), h("p", { text: note })) : null,
        summary, sentList, moreSlot,
        h("button", { type: "button", class: "btn weak block al-more-send", onclick: () => go("send?mode=notify") }, icon("send"), h("span", { text: "새 알림 보내기" })),
        autoSection);
      paintManual();
    }

    /** 직접 보낸 알림 한 줄: 받는 사람·때·방법·글 + [다시 보내기]·[지우기](AUG-06). */
    function sentRow(n, repaint) {
      const names = (n.recipients || []).map((r) => r.name).filter(Boolean).join(", ");
      const kinds = new Set((n.recipients || []).map((r) => r.kind));
      const who = [kinds.has("helper") ? "조력자" : "", kinds.has("counselor") ? "상담하는 곳" : ""].filter(Boolean).join("·");
      const tags = [h("span", { class: "tag" }, icon(NOTICE_CHANNEL_ICON[n.channel] || "send"), h("span", { text: NOTICE_CHANNEL_KO[n.channel] || "알림" })),
        (n.txn_ids || []).length ? h("span", { class: "tag" }, icon("list"), h("span", { text: `거래 ${nf.format(n.txn_ids.length)}건` })) : null];
      const li = h("li", { class: "al-sent-item" });
      const del = n.id ? h("button", { type: "button", class: "btn sm al-del", "aria-label": `${names || "받는 사람"}에게 보낸 알림 기록 지우기` }, icon("trash"), h("span", { text: "지우기" })) : null;
      if (del) {
        del.addEventListener("click", async () => {
          if (del.getAttribute("aria-busy") === "true") return;
          const ok = await confirmSheet({ title: "이 기록을 지울까요?", lines: ["보낸 알림 목록에서만 지워요.", "문자·메일 앱에 남은 글은 그대로예요."],
            confirmText: "기록 지우기", cancelText: "아니요", danger: true });
          if (!ok || !del.isConnected) return;
          del.setAttribute("aria-busy", "true");
          del.setAttribute("aria-disabled", "true");
          try {
            await ctx.req("POST", "/api/notices/remove", { id: String(n.id) });
            n.__gone = true;
            const next = li.nextElementSibling || li.previousElementSibling;
            li.remove();
            delete cache.sent;
            delete cache.cards;   // 알렸어요 표시가 바뀔 수 있다
            repaint();
            toast("보낸 알림 기록을 지웠어요.");
            const focusTo = next && next.isConnected ? next.querySelector(".al-del") : panel;
            if (focusTo) focusTo.focus();
          } catch (e) {
            if (e !== STALE) toast(friendlyError(e).message || "지우지 못했어요. 다시 해 주세요.", "error");
          } finally {
            if (del.isConnected) { del.removeAttribute("aria-busy"); del.removeAttribute("aria-disabled"); }
          }
        });
      }
      return fill(li,
        h("div", { class: "row al-sent-row" },
          h("span", { class: "row-icon blue" }, icon(NOTICE_CHANNEL_ICON[n.channel] || "send")),
          h("span", { class: "row-main" },
            h("span", { class: "row-title", text: names || "받는 사람" }),
            subParts([who, ...whenParts(n.created_at)]))),
        h("div", { class: "al-sent-body" },
          h("div", { class: "row-tags" }, tags),
          messageBlock(n),
          n.id ? h("div", { class: "al-row-actions al-sent-actions" },
            h("a", { class: "btn sm weak", href: `#/send?mode=notify&resend=${encodeURIComponent(n.id)}` }, icon("refresh"), h("span", { text: "다시 보내기" })),
            del) : null));
    }

    /** 조력자 설정대로 적어 둔 기록 한 줄(보내지 않았음): [알림 보내기로 보내기]로 그 조력자·거래를 미리 고른다. */
    function autoRow(n) {
      const lv = LEVEL[n.level] || null;
      const q = new URLSearchParams({ mode: "notify" });
      if (n.txn_id) q.set("txn", n.txn_id);
      if (n.helper_id) q.set("helper", n.helper_id);
      return h("li", { class: "al-sent-item al-auto-item" },
        h("div", { class: "row al-sent-row" },
          h("span", { class: `row-icon ${n.level === "high" ? "red" : "orange"}` }, icon("edit")),
          h("span", { class: "row-main" },
            h("span", { class: "row-title", text: n.helper_name || "조력자" }),
            subParts(["조력자", ...whenParts(n.created_at)]))),
        h("div", { class: "al-sent-body" },
          h("div", { class: "row-tags" },
            h("span", { class: "tag al-unsent" }, icon("edit"), h("span", { text: "적어 둠 · 아직 안 보냄" })),
            lv && n.level !== "none" ? levelBadge(n.level) : null),
          messageBlock(n),
          h("div", { class: "al-row-actions al-sent-actions" },
            h("a", { class: "btn sm weak", href: `#/send?${q.toString()}` }, icon("send"), h("span", { text: "알림 보내기로 보내기" })))));
    }

    /** 보낸 글(길면 접어 두고 글 모두 보기). */
    function messageBlock(n) {
      const message = String(n.message || "");
      if (!message) return null;
      const msgEl = h("p", { class: "al-msg", "data-nosplit": true, text: message });
      if (message.length <= LONG_MESSAGE && (message.match(/\n/g) || []).length <= 2) return msgEl;
      msgEl.classList.add("clamp");
      const id = `al-msg-${String(n.id || n.created_at || Math.random()).replace(/[^\w-]/g, "")}${n.kind === "manual" ? "" : "-a"}`;
      msgEl.id = id;
      const toggle = h("button", { type: "button", class: "btn sm ghost al-msg-toggle", "aria-expanded": "false", "aria-controls": id }, h("span", { text: "글 모두 보기" }));
      toggle.addEventListener("click", () => {
        const open = toggle.getAttribute("aria-expanded") !== "true";
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
        msgEl.classList.toggle("clamp", !open);
        toggle.firstChild.textContent = open ? "글 접기" : "글 모두 보기";
      });
      return h("div", { class: "al-msg-wrap" }, msgEl, toggle);
    }

    // ================= 상담 안내 띠 =================
    function renderBand(hint) {
      if (hint && typeof hint === "object") {
        if (hint.suggest) paintBand(hint.recent_high, hint.threshold);
        return;
      }
      fallbackBand();
    }

    /** /api/cards에 상담 안내 정보가 없을 때: 동의 + 마지막 거래 기준 30일 꼭 확인할 거래 수로 직접 판단. */
    async function fallbackBand() {
      try {
        const [consent, high, last] = await Promise.all([
          ctx.req("GET", "/api/consent"),
          ctx.req("GET", "/api/transactions?level=high&limit=0"),
          ctx.req("GET", "/api/transactions?limit=1"),
        ]);
        if (!consent || !consent.counseling_referral) return;
        const lastTs = parseTs(((last.items || [])[0] || {}).txn ? last.items[0].txn.ts : "");
        if (!lastTs) return;
        const from = lastTs.getTime() - COUNSEL_DAYS * 86400000;
        const n = (high.items || []).filter((it) => {
          const d = parseTs(it.txn.ts);
          return !it.reviewed && d && d.getTime() > from && d.getTime() <= lastTs.getTime();
        }).length;
        if (n >= COUNSEL_MIN) paintBand(n, COUNSEL_MIN);
      } catch (e) { /* 띠는 덤이다: 못 불러오면 보이지 않는다 */ }
    }

    function paintBand(count, threshold) {
      fill(band, h("section", { class: "al-band", "aria-labelledby": "al-band-title" },
        h("span", { class: "al-band-icon" }, icon("building")),
        h("div", { class: "al-band-main" },
          h("h3", { id: "al-band-title", text: "상담하는 곳에 알려 볼까요?" }),
          h("p", { text: `꼭 확인할 거래가 ${COUNSEL_DAYS}일 동안 ${nf.format(count || threshold || COUNSEL_MIN)}건 있었어요. 상담하는 곳과 함께 살펴볼 수 있어요.` }),
          h("button", { type: "button", class: "btn sm primary al-band-btn", onclick: () => go("send?to=counselors") },
            icon("send"), h("span", { text: "상담하는 곳에 알리기" })))));
    }

    fill(panel, skeleton(2));
    try {
      const c = await ctx.req("GET", "/api/consent");
      ctx.session.consent = c;
      monitoring = Boolean(c && c.monitoring);
    } catch (e) {
      if (e === STALE) return;   // 동의를 못 읽으면 그대로 불러 보고, 오류는 각 탭이 알린다
    }
    await show();
    // 다른 탭 건수와 상담 안내 띠: 보이는 탭을 그린 뒤 조용히 불러온다
    for (const t of TABS) if (t.value !== tab) get(t.value).catch(() => {});
  },
};

/** 지금 할 수 있는 일(J6): 신호마다 1~2줄, 겹치는 줄은 한 번만. */
function nextSteps(item) {
  const codes = (item.signals || []).length ? item.signals : ["anomaly"];
  const lines = [];
  for (const c of codes) for (const line of NEXT_STEPS[c] || NEXT_STEPS.anomaly) if (!lines.includes(line)) lines.push(line);
  return lines.slice(0, 4);
}

/** 날짜 머리 없이 보이는 거래 줄(담은 거래): 이름과 금액 한 줄 → 날짜·방법 → 표시 이름. notify.js 거래 줄과 같은 모양. */
function datedTxn(item) {
  const t = item.txn;
  const out = t.direction === "out";
  const d = parseTs(t.ts);
  const tone = item.level === "high" ? "red" : item.level === "caution" ? "orange" : out ? "" : "blue";
  const tags = [item.level && item.level !== "none" ? levelBadge(item.level) : null,
    ...txnSignals(item).map((s) => h("span", { class: "tag" }, icon(s.icon), h("span", { text: s.text }))),
    reviewBadge(item), notifiedBadge(item)].filter(Boolean);
  return h("div", { class: "np-txn al-txn" },
    h("span", { class: `row-icon ${tone}`.trim() }, icon(CHANNEL_ICON[t.channel] || "cash")),
    h("span", { class: "np-txn-main" },
      h("span", { class: "np-txn-top" },
        h("span", { class: "row-title", text: t.counterparty || "(이름 없음)" }),
        h("span", { class: `row-amount${out ? "" : " in"}`, text: txnAmount(t) })),
      subParts([d ? `${d.getMonth() + 1}월 ${d.getDate()}일` : "", d ? formatTime(d) : "", CHANNEL_KO[t.channel] || t.channel]),
      tags.length ? h("span", { class: "row-tags" }, tags) : null));
}

/** segTabs 버튼에 건수를 붙이거나 바꾼다. */
function setTabCount(tabsEl, value, n) {
  const btn = tabsEl.querySelector(`[data-v="${value}"]`);
  if (!btn) return;
  let c = btn.querySelector(".seg-count");
  if (!c) { c = h("span", { class: "seg-count" }); btn.append(c); }
  c.textContent = nf.format(n);
  btn.setAttribute("aria-label", `${btn.querySelector("span").textContent.replace(/\s+/g, " ")} ${nf.format(n)}건`);
}

