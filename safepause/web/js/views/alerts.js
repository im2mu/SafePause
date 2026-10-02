/* 알림: 걱정되는 거래(쉬운 말 카드) · 담은 거래 · 보낸 알림. 카드·담은 거래마다 알리기(→ 알림 보내기).
 * - 탭은 주소 뒤 tab 값(cards|flags|sent)으로 고른다. 옛 이름 risky·flagged도 받는다.
 * - 상담 안내 띠: 상담하는 곳에 알려 주기 동의 + 꼭 확인할 거래가 30일 동안 기준 이상이면 → 알림 보내기(상담하는 곳).
 */
import { h, icon, fill, setText, toast, announce, skeleton, segTabs } from "../ui.js";
import { nf, formatTime, parseTs, deviceWord } from "../format.js";
import { alertCard, txnAmount, txnSignals, levelBadge, flaggedBadge, errorNotice, subParts, whenParts } from "../components.js";
import { LEVEL, CHANNEL_KO, CHANNEL_ICON, NOTICE_CHANNEL_KO, NOTICE_CHANNEL_ICON } from "../labels.js";
import { STALE } from "../api.js";

const TABS = [
  { value: "cards", label: "걱정되는 거래" },
  { value: "flags", label: "담은 거래" },
  { value: "sent", label: "보낸 알림" },
];
const ALIAS = { risky: "cards", flagged: "flags" };
const MAX_SEND = 5;            // 알림 보내기에서 한 번에 고를 수 있는 거래 수(notify.js와 같음)
const COUNSEL_DAYS = 30;       // 상담 안내 기준 기간(api settings.window_long_days)
const COUNSEL_MIN = 3;         // 상담 안내 기준 건수(api settings.high_repeat_for_counseling)
const LONG_MESSAGE = 90;       // 이보다 긴 글은 접어 두고 글 모두 보기

/** #/send?txn=a&txn=b */
function sendHref(ids) {
  return "#/send?" + ids.map((id) => "txn=" + encodeURIComponent(id)).join("&");
}

/** 404인데 쉬운 말 안내가 없으면(새 기능을 아직 못 쓰는 엔진) 쉬운 말로 바꾼다. */
function friendlyError(e) {
  if (e && e.status === 404 && !/[가-힣]/.test(String(e.message || ""))) {
    return Object.assign(new Error("이 목록을 아직 불러올 수 없어요. 잠시 뒤 다시 해 주세요."), { status: 404 });
  }
  return e;
}

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
    const PATHS = { cards: "/api/cards?limit=30", flags: "/api/flags", sent: "/api/notices" };
    let seq = 0;
    let bandDone = false;
    let monitoring = true;   // 거래 살펴보기 동의(꺼져 있으면 걱정되는 거래·담은 거래를 부르지 않는다)

    const band = h("div", { class: "al-band-slot" });
    const panel = h("div", { class: "al-panel", id: "alerts-panel", role: "tabpanel", tabindex: "-1" });
    // 건수는 불러온 뒤 채운다(빈 칸 자리를 미리 둬서 글자가 밀리지 않게)
    const tabs = segTabs(TABS.map((t) => ({ ...t, count: "" })), tab, (v) => { tab = v; ctx.replaceParams({ tab: v }); show(); },
      { label: "알림 보기", controls: "alerts-panel" });
    tabs.el.classList.add("al-tabs");

    fill(main,
      h("h2", { class: "page-title", tabindex: "-1", text: "알림" }),
      h("p", { class: "page-sub", text: "걱정되는 거래를 모아 보고, 조력자와 상담하는 곳에 알려요." }),
      band, h("div", { class: "al-tabs-wrap" }, tabs.el), panel);

    function get(name, force = false) {
      if (!monitoring && name !== "sent") return Promise.resolve({ consentOff: true });
      if (force || !cache[name]) {
        const p = ctx.req("GET", PATHS[name]);
        cache[name] = p;
        p.then((d) => { if (cache[name] === p) countOf(name, d); }).catch(() => { if (cache[name] === p) delete cache[name]; });
      }
      return cache[name];
    }

    function countOf(name, d) {
      if (d.consentOff) return;
      const n = name === "cards" ? (d.total ?? (d.items || []).length) : (d.items || []).length;
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

    // ---- 걱정되는 거래: 쉬운 말 카드 + 알리기·담기 ----
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
      fill(panel,
        h("p", { class: "al-summary", text: total > items.length
          ? `걱정되는 거래 ${nf.format(total)}건 가운데 최근 ${nf.format(items.length)}건이에요.`
          : `걱정되는 거래가 ${nf.format(total)}건 있어요.` }),
        h("div", { class: "al-cards" }, items.map((item) => {
          const holder = { el: null };
          const card = alertCard(item, { actions: [
            h("a", { class: "btn sm weak al-send", href: `#/send?txn=${encodeURIComponent(item.txn.id)}` }, icon("send"), h("span", { text: "알리기" })),
            flagToggle(item, (on) => {
              const head = holder.el && holder.el.querySelector(".alert-head");
              const badge = head && head.querySelector(".badge.info");
              if (on && head && !badge) head.append(flaggedBadge());
              if (!on && badge) badge.remove();
            }),
          ] });
          holder.el = card;
          return card;
        })));
    }

    /** 카드의 담기 ↔ 담음 토글(POST /api/flags, /api/flags/remove). */
    function flagToggle(item, onChange) {
      let on = Boolean(item.flagged);
      const ic = h("span", { class: "btn-ic" });
      const text = h("span");
      const btn = h("button", { type: "button", class: "btn sm al-flag-btn", "aria-pressed": "false" }, ic, text);
      function paint() {
        btn.setAttribute("aria-pressed", on ? "true" : "false");
        ic.replaceChildren(icon(on ? "bookmark-fill" : "bookmark"));
        text.textContent = on ? "담음" : "담기";
      }
      btn.addEventListener("click", async () => {
        if (btn.getAttribute("aria-busy") === "true") return;
        btn.setAttribute("aria-busy", "true");
        const next = !on;
        try {
          const r = await ctx.req("POST", next ? "/api/flags" : "/api/flags/remove", { txn_id: item.txn.id });
          on = next;
          item.flagged = next;
          paint();
          onChange(next);
          delete cache.flags;   // 담은 거래 탭은 다음에 새로 불러온다
          if (r && Number.isInteger(r.count)) setTabCount(tabs.el, "flags", r.count);
          toast(next ? "담은 거래에 넣었어요." : "담은 거래에서 뺐어요.");
        } catch (e) {
          if (e !== STALE) toast(friendlyError(e).message || "담지 못했어요. 다시 해 주세요.", "error");
        } finally {
          if (btn.isConnected) btn.removeAttribute("aria-busy");
        }
      });
      paint();
      return btn;
    }

    // ---- 담은 거래: 알리기 · 빼기 ----
    function showFlags(d) {
      const items = (d.items || []).filter((x) => x && x.item);
      if (!items.length) {
        fill(panel, h("div", { class: "empty" }, icon("bookmark"),
          h("b", { text: "담은 거래가 없어요" }),
          h("p", { text: "내 거래에서 거래를 누르면 알림 목록에 담을 수 있어요." }),
          h("button", { type: "button", class: "btn weak", onclick: () => go("txns") }, icon("list"), h("span", { text: "내 거래 보기" }))));
        return;
      }
      const ids = items.map((x) => x.item.txn.id);
      const head = h("p", { class: "al-summary" });
      const sendAll = h("a", { class: "btn primary block al-send-all", href: sendHref(ids.slice(0, MAX_SEND)) }, icon("send"), h("span"));
      const list = h("ul", { class: "list al-flags", "aria-label": "담은 거래" });
      function paintHead() {
        const n = list.children.length;
        setText(head, `담은 거래가 ${nf.format(n)}건 있어요.`);
        const left = Array.from(list.children).map((li) => li.dataset.id).slice(0, MAX_SEND);
        sendAll.setAttribute("href", sendHref(left));
        sendAll.lastChild.textContent = n > MAX_SEND ? `최근 ${MAX_SEND}건 한 번에 알리기` : "담은 거래 한 번에 알리기";
        setTabCount(tabs.el, "flags", n);
        if (!n) showFlags({ items: [] });
      }
      for (const x of items) {
        const item = x.item;
        const id = item.txn.id;
        const li = h("li", { class: "al-flag", "data-id": id });
        const out = h("button", { type: "button", class: "btn sm", onclick: async () => {
          if (out.getAttribute("aria-busy") === "true") return;
          out.setAttribute("aria-busy", "true");
          try {
            await ctx.req("POST", "/api/flags/remove", { txn_id: id });
            const next = li.nextElementSibling || li.previousElementSibling;
            li.remove();
            delete cache.cards;   // 카드의 담음 표시가 바뀌었다
            cache.flags = Promise.resolve({ items: items.filter((y) => list.querySelector(`[data-id="${CSS.escape(y.item.txn.id)}"]`)) });
            paintHead();
            announce("담은 거래에서 뺐어요.");
            const focusTo = next && next.isConnected ? next.querySelector(".al-out") : panel;
            if (focusTo) focusTo.focus();
          } catch (e) {
            if (e !== STALE) toast(friendlyError(e).message || "빼지 못했어요. 다시 해 주세요.", "error");
          } finally {
            if (out.isConnected) out.removeAttribute("aria-busy");
          }
        } }, icon("minus"), h("span", { text: "빼기" }));
        out.classList.add("al-out");
        out.setAttribute("aria-label", `${item.txn.counterparty || "이름 없음"} 거래 빼기`);
        append(li, datedTxn(item),
          h("div", { class: "al-row-actions" },
            h("a", { class: "btn sm weak", href: sendHref([id]), "aria-label": `${item.txn.counterparty || "이름 없음"} 거래 알리기` }, icon("send"), h("span", { text: "알리기" })),
            out));
        list.append(li);
      }
      fill(panel, head, sendAll, list);
      paintHead();
    }

    // ---- 보낸 알림: 직접 보낸 기록 + 자동 기록 ----
    function showSent(d) {
      const items = d.items || [];
      const note = d.delivery_note ? String(d.delivery_note).replace(/^이 기기/, deviceWord()) : "";
      const noteBox = note ? h("div", { class: "notice" }, icon("info"), h("p", { text: note })) : null;
      if (!items.length) {
        fill(panel, noteBox, h("div", { class: "empty" }, icon("send"),
          h("b", { text: "아직 보낸 알림이 없어요" }),
          h("p", { text: "알림 보내기에서 조력자와 상담하는 곳에 알릴 수 있어요." }),
          h("button", { type: "button", class: "btn weak", onclick: () => go("send?mode=notify") }, icon("send"), h("span", { text: "알림 보내기" }))));
        return;
      }
      fill(panel, noteBox,
        h("p", { class: "al-summary", text: `보낸 알림 ${nf.format(items.length)}건이에요.` }),
        h("ul", { class: "list al-sent", "aria-label": "보낸 알림" }, items.slice(0, 100).map(sentRow)),
        h("button", { type: "button", class: "btn weak block al-more-send", onclick: () => go("send?mode=notify") }, icon("send"), h("span", { text: "새 알림 보내기" })));
    }

    function sentRow(n) {
      const manual = n.kind === "manual";
      const names = manual
        ? (n.recipients || []).map((r) => r.name).filter(Boolean).join(", ")
        : (n.helper_name || "조력자");
      const kinds = manual ? new Set((n.recipients || []).map((r) => r.kind)) : new Set(["helper"]);
      const who = [kinds.has("helper") ? "조력자" : "", kinds.has("counselor") ? "상담하는 곳" : ""].filter(Boolean).join("·");
      const lv = LEVEL[n.level] || null;
      const tone = manual ? "blue" : n.level === "high" ? "red" : "orange";
      const tags = manual
        ? [h("span", { class: "tag" }, icon(NOTICE_CHANNEL_ICON[n.channel] || "send"), h("span", { text: NOTICE_CHANNEL_KO[n.channel] || "알림" })),
          (n.txn_ids || []).length ? h("span", { class: "tag" }, icon("list"), h("span", { text: `거래 ${nf.format(n.txn_ids.length)}건` })) : null]
        : [h("span", { class: "tag" }, icon("bell"), h("span", { text: "자동 기록" })), lv && n.level !== "none" ? levelBadge(n.level) : null];
      const message = String(n.message || "");
      const msgEl = h("p", { class: "al-msg", "data-nosplit": true, text: message });
      let toggle = null;
      if (message.length > LONG_MESSAGE || (message.match(/\n/g) || []).length > 2) {
        msgEl.classList.add("clamp");
        const id = `al-msg-${String(n.id || n.created_at || Math.random()).replace(/[^\w-]/g, "")}`;
        msgEl.id = id;
        toggle = h("button", { type: "button", class: "btn sm ghost al-msg-toggle", "aria-expanded": "false", "aria-controls": id }, h("span", { text: "글 모두 보기" }));
        toggle.addEventListener("click", () => {
          const open = toggle.getAttribute("aria-expanded") !== "true";
          toggle.setAttribute("aria-expanded", open ? "true" : "false");
          msgEl.classList.toggle("clamp", !open);
          toggle.firstChild.textContent = open ? "글 접기" : "글 모두 보기";
        });
      }
      return h("li", { class: "al-sent-item" },
        h("div", { class: "row al-sent-row" },
          h("span", { class: `row-icon ${tone}` }, icon(manual ? (NOTICE_CHANNEL_ICON[n.channel] || "send") : "bell")),
          h("span", { class: "row-main" },
            h("span", { class: "row-title", text: names || "받는 사람" }),
            subParts([who, ...whenParts(n.created_at)]))),
        h("div", { class: "al-sent-body" },
          h("div", { class: "row-tags" }, tags),
          message ? msgEl : null,
          toggle));
    }

    // ---- 상담 안내 띠 ----
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
          return d && d.getTime() > from && d.getTime() <= lastTs.getTime();
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

/** 날짜 머리 없이 보이는 거래 줄(담은 거래): 이름과 금액 한 줄 → 날짜·방법 → 표시 이름. notify.js 거래 줄과 같은 모양. */
function datedTxn(item) {
  const t = item.txn;
  const out = t.direction === "out";
  const d = parseTs(t.ts);
  const tone = item.level === "high" ? "red" : item.level === "caution" ? "orange" : out ? "" : "blue";
  const tags = [item.level && item.level !== "none" ? levelBadge(item.level) : null,
    ...txnSignals(item).map((s) => h("span", { class: "tag" }, icon(s.icon), h("span", { text: s.text })))].filter(Boolean);
  return h("div", { class: "np-txn al-txn" },
    h("span", { class: `row-icon ${tone}`.trim() }, icon(CHANNEL_ICON[t.channel] || "cash")),
    h("span", { class: "np-txn-main" },
      h("span", { class: "np-txn-top" },
        h("span", { class: "row-title", text: t.counterparty || "(이름 없음)" }),
        h("span", { class: `row-amount${out ? "" : " in"}`, text: txnAmount(t) })),
      subParts([d ? `${d.getMonth() + 1}월 ${d.getDate()}일 ${formatTime(d)}` : "", CHANNEL_KO[t.channel] || t.channel]),
      tags.length ? h("span", { class: "row-tags" }, tags) : null));
}

function append(el, ...children) {
  for (const c of children) if (c) el.append(c);
  return el;
}

/** segTabs 버튼에 건수를 붙이거나 바꾼다. */
function setTabCount(tabsEl, value, n) {
  const btn = tabsEl.querySelector(`[data-v="${value}"]`);
  if (!btn) return;
  let c = btn.querySelector(".seg-count");
  if (!c) { c = h("span", { class: "seg-count" }); btn.append(c); }
  c.textContent = nf.format(n);
  btn.setAttribute("aria-label", `${btn.querySelector("span").textContent} ${nf.format(n)}건`);
}
