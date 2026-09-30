/* 처음 켰을 때: 무엇을 하는 앱인지 → 동의 세 가지(모두 꺼짐에서 시작, 따로 고름) → 누가 동의했는지. */
import { h, icon, fill, busy, toast } from "../ui.js";
import { errorNotice } from "../components.js";
import { STALE, MODE } from "../api.js";

export default {
  title: "시작하기",
  noNav: true,
  noAppbar: true,
  async render(ctx) {
    const { main, go } = ctx;
    const where = MODE === "engine" ? "이 기기" : "이 컴퓨터";
    const choice = { monitoring: false, helper_alerts: false, counseling_referral: false, given_by: "self" };
    let step = 0;
    main.className = "main no-nav onboard";

    function later() {
      try { sessionStorage.setItem("safepause.onboard.later", "1"); } catch (e) { /* 무시 */ }
      go("home", { replace: true });
    }

    function dots() { return h("div", { class: "steps-dots", "aria-hidden": "true" }, [0, 1, 2].map((i) => h("i", { class: i === step ? "on" : "" }))); }

    function show() {
      if (step === 0) {
        fill(main, h("div", { class: "onboard-body" }, dots(),
          h("div", { class: "onboard-hero" }, icon("stop")),
          h("h1", { tabindex: "-1", text: "돈을 보내기 전에 잠깐 멈춰요." }),
          h("p", { class: "muted", text: "걱정되는 거래가 있으면 쉬운 말과 그림으로 한 번 더 물어봐요. 결정은 내가 해요." }),
          h("ul", { class: "promise" },
            h("li", null, icon("shield"), h("span", { text: "SafePause는 막지 않아요. 걱정되면 한 번 더 물어볼 뿐이에요." })),
            h("li", null, icon("lock"), h("span", { text: `살펴보는 일은 ${where} 안에서만 해요.` })),
            h("li", null, icon("toggle"), h("span", { text: "무엇을 할지 내가 정해요. 언제든지 끌 수 있어요." })))),
        h("div", { class: "onboard-foot" },
          h("button", { type: "button", class: "btn primary big block", text: "다음", onclick: () => { step = 1; show(); } }),
          h("button", { type: "button", class: "btn ghost big block", text: "나중에 할게요", onclick: later })));
      } else if (step === 1) {
        const items = [
          ["monitoring", "거래 살펴보기", "내가 돈을 쓰고 보내는 것을 살펴봐요."],
          ["helper_alerts", "조력자에게 알리기", "위험이 클 때 내가 고른 조력자에게 알려요."],
          ["counseling_referral", "상담하는 곳 알려 주기", "꼭 확인할 일이 30일 동안 3번 이상 생기면 상담하는 곳을 알려 줘요."],
        ];
        fill(main, h("div", { class: "onboard-body" }, dots(),
          h("h1", { tabindex: "-1", text: "무엇을 해도 될까요?" }),
          h("p", { class: "muted", style: "margin-bottom:1rem", text: "하나씩 골라요. 처음에는 모두 꺼져 있어요." }),
          h("div", { class: "list" }, items.map(([key, title, desc]) => {
            const sw = h("button", { type: "button", class: "switch", role: "switch", "aria-checked": choice[key] ? "true" : "false", "aria-label": title,
              onclick: () => { choice[key] = !choice[key]; sw.setAttribute("aria-checked", choice[key] ? "true" : "false"); } });
            return h("div", { class: "switch-row" }, h("div", { class: "row-main" }, h("h3", { text: title }), h("p", { text: desc })), sw);
          }))),
        h("div", { class: "onboard-foot" },
          h("button", { type: "button", class: "btn primary big block", text: "다음", onclick: () => { step = 2; show(); } }),
          h("button", { type: "button", class: "btn ghost big block", text: "앞으로", onclick: () => { step = 0; show(); } })));
      } else {
        const err = h("div");
        const radios = [["self", "나(본인)"], ["legal_representative", "법정대리인"]].map(([v, t]) => {
          const input = h("input", { type: "radio", name: "ob-given", value: v, checked: choice.given_by === v, onchange: () => { choice.given_by = v; } });
          return h("label", null, input, h("span", { text: t }));
        });
        fill(main, h("div", { class: "onboard-body" }, dots(),
          h("h1", { tabindex: "-1", text: "누가 동의했나요?" }),
          h("p", { class: "muted", style: "margin-bottom:1rem", text: "동의한 사람을 기록해요. 나중에 '동의'에서 바꿀 수 있어요." }),
          h("div", { class: "segmented", role: "radiogroup", "aria-label": "누가 동의했나요?" }, radios),
          h("div", { class: "notice", style: "margin-top:1.25rem" }, icon("info"), h("p", { text: "연습 화면이에요. 실제로 돈이 나가지 않아요." })),
          err),
        h("div", { class: "onboard-foot" },
          h("button", {
            type: "button", class: "btn primary big block",
            onclick: (e) => busy(e.currentTarget, async () => {
              try {
                const c = await ctx.req("PUT", "/api/consent", { ...choice });
                ctx.session.consent = c;
                toast("설정을 저장했어요.");
                go(choice.monitoring ? "txns" : "home", { replace: true });
              } catch (e2) {
                if (e2 === STALE) return;
                fill(err, errorNotice(e2, null));
              }
            }),
          }, icon("check"), h("span", { text: "시작하기" })),
          h("button", { type: "button", class: "btn ghost big block", text: "앞으로", onclick: () => { step = 1; show(); } })));
      }
      main.querySelector("h1")?.focus();
    }
    show();
  },
};
