/* 동의: 세 가지를 따로 켜고 끄며, 끄면 바로 멈춘다(S18·S37 즉시 철회). 맨 아래에 모두 지우기.
 * 거래 살펴보기를 끄거나 모두 지울 때는 화면 데이터 세대를 올려, 요청 중이던 옛 거래 목록이 다시 그려지지 않게 한다(리뷰 H1). */
import { h, icon, fill, setText, toast, announce, skeleton, busy, confirmSheet, paragraphs } from "../ui.js";
import { formatWhen, deviceWord, keepUnits } from "../format.js";
import { errorNotice } from "../components.js";
import { STALE } from "../api.js";
import { clearBankApp } from "./bankapp.js";

// 설명(lines)은 문단 목록이다: 문단 하나 = 문장 배열(문장마다 한 줄, 같은 문단은 촘촘하게)
const ITEMS = [
  { key: "monitoring", icon: "chart", title: "거래 살펴보기",
    lines: [["내 거래를 살펴보고 걱정되는 거래를 찾아요.", `살펴보는 일은 ${deviceWord()} 안에서만 해요.`]] },
  // 실제 동작(policy.decide·notify_suggest): 조력자 설정(등급·범위·자동으로 알리기)에 맞는 사람을 알림 보내기에서 미리 골라 두고,
  // 돈 보내기에서 걱정되는 거래를 확인하면 알릴 수 있게 적어 둔다(적어 둔 기록). 보내기는 본인이 문자·메일 앱에서 누른다
  { key: "helper_alerts", icon: "users", title: "조력자에게 알리기",
    lines: [["걱정되는 거래를 알릴 때 조력자 설정에 맞는 사람을 미리 골라 둬요.", "돈 보내기에서 걱정되는 거래를 확인하면 알릴 수 있게 적어 둬요."],
      ["보내기는 내가 문자·메일 앱에서 눌러요.", "이 스위치를 꺼도 알림 보내기에서 직접 알릴 수 있어요."]],
    link: { href: "#/more/helpers", icon: "users", text: "조력자 정하기" } },
  // 상담하는 곳으로 저절로 가는 것은 없다(C2): 알릴 때가 되면 알림 탭 띠와 알림 보내기 추천으로 알려 준다
  { key: "counseling_referral", icon: "building", title: "상담하는 곳에 알려 주기",
    lines: [["상담하는 곳에 알려 줘요.", "알릴 때가 되면 알림 탭에서 알려 드리고, 알림 보내기에서 상담하는 곳을 추천해요.", "보내기는 내가 눌러요."]],
    bulletsHead: "알릴 때는 이래요.",
    bullets: ["꼭 확인할 일이 30일 동안 3번 이상 생길 때", "알릴 조력자가 모두 돈을 받는 사람일 때"],
    link: { href: "#/more/counselors", icon: "building", text: "상담하는 곳 정하기" } },
];
// 모두 지우기에서 함께 지워지는 것(서버 파일 + 이 휴대폰 브라우저 저장소의 내 은행 앱·알림에 쓰는 내 이름)
// 서버 저장 파일(store.STORE_FILES)마다 하나 이상: 거래·담은 거래·내가 확인한 거래(reviews)·돈 보내기 확인 기록(decisions, IA-7)·알림 기록
const WIPED = ["동의한 것", "조력자", "상담하는 곳", "거래", "담은 거래", "내가 확인한 거래", "돈 보내기 확인 기록", "보낸 알림 기록", "내 은행 앱", "알림에 쓰는 내 이름"];
// 알림 보내기에서 적은 내 이름(수정 계획 1-B, notify.js와 같은 열쇠)
const MY_NAME_KEY = "safepause.myName";

export default {
  title: "동의",
  back: "more",
  tab: "more",
  async render(ctx) {
    const { main, go } = ctx;
    const list = h("div", { class: "list" }, skeleton(1));
    const updated = h("p", { class: "muted consent-updated" });
    const givenBy = h("div", { class: "segmented", role: "radiogroup", "aria-label": "누가 동의했나요?" });
    const status = h("div", { role: "status" });
    const wipeOut = h("div", { "aria-live": "polite" });
    fill(main,
      h("h2", { class: "page-title", tabindex: "-1", text: "동의" }),
      h("p", { class: "page-sub", text: "SafePause가 무엇을 해도 되는지 내가 정해요. 언제든지 끌 수 있어요. 끄면 바로 멈춰요." }),
      list, updated,
      h("h3", { class: "section-title", text: "누가 동의했나요?" }), givenBy, status,

      h("h3", { class: "section-title", text: "모두 지우기" }),
      h("div", { class: "card wipe-card" },
        h("p", { text: `${deviceWord()}에 저장한 것을 모두 지워요. 지우면 되돌릴 수 없어요.` }),
        h("ul", { class: "wipe-items", "aria-label": "함께 지워지는 것" }, WIPED.map((t) => h("li", { class: "tag", text: t }))),
        h("button", { type: "button", class: "btn danger-weak big block", onclick: (e) => busy(e.currentTarget, wipe) },
          icon("trash"), h("span", { text: "모두 지우기" }))),
      wipeOut);

    const switches = {};

    function render(c) {
      ctx.session.consent = c;
      if (!list.querySelector(".switch-row")) {
        fill(list, ITEMS.map((it) => {
          const titleId = `c-${it.key}-title`, descId = `c-${it.key}-desc`;
          const sw = h("button", { type: "button", class: "switch", role: "switch", "aria-checked": "false", "aria-labelledby": titleId, "aria-describedby": descId,
            onclick: () => toggle(it, sw) });
          switches[it.key] = sw;
          // 윗줄: 아이콘 · 이름 · 스위치, 아랫줄: 설명(좁은 화면에서도 스위치가 이름 옆에 남게)
          return h("div", { class: "switch-row consent-row" },
            h("div", { class: "consent-head" },
              h("span", { class: "row-icon blue" }, icon(it.icon)),
              h("h3", { id: titleId, text: it.title }),
              sw),
            h("div", { class: "consent-body" },
              h("div", { id: descId }, paragraphs(it.lines).map((t) => h("p", { text: t })),
                it.bulletsHead ? h("p", { class: "consent-bullets-head", text: it.bulletsHead }) : null,
                it.bullets ? h("ul", { class: "bullets consent-bullets" }, it.bullets.map((b) => h("li", { text: b }))) : null),
              it.link ? h("a", { class: "btn sm weak consent-link", href: it.link.href }, icon(it.link.icon), h("span", { text: it.link.text })) : null));
        }));
        fill(givenBy, [["self", "나(본인)"], ["legal_representative", "법정대리인"]].map(([v, t]) => {
          const input = h("input", { type: "radio", name: "given_by", value: v, onchange: () => changeGivenBy(v) });
          return h("label", null, input, h("span", { text: t }));
        }));
      }
      for (const it of ITEMS) switches[it.key].setAttribute("aria-checked", c[it.key] ? "true" : "false");
      for (const r of givenBy.querySelectorAll("input")) r.checked = r.value === (c.given_by || "self");
      setText(updated, c.updated_at ? keepUnits(`마지막으로 바꾼 때: ${formatWhen(c.updated_at)}`) : "아직 아무것도 켜지 않았어요. 모두 꺼져 있어요.");   // 문장마다 한 줄(C5)
    }

    async function toggle(it, sw) {
      if (sw.getAttribute("aria-busy") === "true") return;
      const next = sw.getAttribute("aria-checked") !== "true";
      sw.setAttribute("aria-busy", "true");
      sw.setAttribute("aria-checked", next ? "true" : "false");   // 누르는 즉시 보여 준다(리뷰 L2)
      if (it.key === "monitoring" && !next) ctx.session.bumpEpoch();   // 끄는 즉시 옛 분석 응답을 버린다(리뷰 H1)
      try {
        render(await ctx.req("PUT", "/api/consent", { [it.key]: next }));
        status.replaceChildren();   // 앞서 난 오류 안내를 지운다
        const msg = next ? `${it.title}: 켰어요.` : `${it.title}: 껐어요. 바로 멈췄어요.`;
        toast(msg);
        announce(msg);
      } catch (e) {
        if (e === STALE) return;
        fill(status, errorNotice(e, go));
        await reload();   // 서버 값으로 되돌린다(리뷰 L1)
      } finally {
        sw.removeAttribute("aria-busy");
      }
    }

    async function changeGivenBy(value) {
      try {
        render(await ctx.req("PUT", "/api/consent", { given_by: value }));
        status.replaceChildren();
        toast(value === "self" ? "본인이 동의했어요." : "법정대리인이 동의했어요.");
      } catch (e) {
        if (e === STALE) return;
        fill(status, errorNotice(e, go));
        await reload();   // 저장되지 않은 선택이 남지 않게(리뷰 L1)
      }
    }

    // 모두 지우기(즉시 철회권): 확인 → 세대 올리기 → 지우기 → 꺼진 동의로 다시 그림
    async function wipe() {
      const ok = await confirmSheet({
        title: "정말 모두 지울까요?", lines: ["되돌릴 수 없어요."], confirmText: "네, 지울래요", cancelText: "아니요", danger: true,
      });
      if (!ok) return;
      ctx.session.bumpEpoch();   // 지우는 즉시 옛 분석 응답을 버린다(리뷰 H1)
      try {
        const r = await ctx.req("POST", "/api/wipe");
        ctx.session.consent = null;
        try { sessionStorage.removeItem("safepause.onboard.later"); } catch (e) { /* 무시 */ }
        clearBankApp();   // 이 휴대폰에 기억한 내 은행 앱도 함께 잊는다
        try { localStorage.removeItem(MY_NAME_KEY); } catch (e) { /* 무시 */ }   // 알림에 쓰는 내 이름도
        fill(wipeOut, h("div", { class: "notice green", role: "status" }, icon("check"), h("p", { text: r.message })));
        toast(r.message);
        announce(r.message);
        await reload();   // 모두 꺼진 동의를 보인다
      } catch (err) {
        if (err === STALE) return;
        fill(wipeOut, errorNotice(err, go));
      }
    }

    async function reload() {
      try { render(await ctx.req("GET", "/api/consent")); } catch (e) { if (e !== STALE) fill(status, errorNotice(e, go)); }
    }
    await reload();
  },
};
