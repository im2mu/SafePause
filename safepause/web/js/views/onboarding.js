/* 처음 켰을 때: 무엇을 하는 앱인지 → 동의 세 가지(모두 꺼짐에서 시작, 따로 고름) → 누가 동의했는지. */
import { h, icon, fill, busy, toast } from "../ui.js";
import { errorNotice } from "../components.js";
import { deviceWord } from "../format.js";
import { STALE } from "../api.js";

export default {
  title: "시작하기",
  noNav: true,
  noAppbar: true,
  async render(ctx) {
    const { main, go } = ctx;
    const where = deviceWord();
    const choice = { monitoring: false, helper_alerts: false, counseling_referral: false, given_by: "self" };
    let step = 0;
    main.className = "main no-nav onboard";

    function later() {
      try { sessionStorage.setItem("safepause.onboard.later", "1"); } catch (e) { /* 무시 */ }
      go("home", { replace: true });
    }

    function dots() { return h("div", { class: "steps-dots", "aria-hidden": "true" }, [0, 1, 2].map((i) => h("i", { class: i === step ? "on" : "" }))); }
    const stepNo = () => h("p", { class: "sr-only", text: `3단계 가운데 ${step + 1}단계` });

    function show() {
      if (step === 0) {
        fill(main, h("div", { class: "onboard-body" }, dots(), stepNo(),
          h("div", { class: "onboard-hero brand-mark" }, icon("logo")),
          h("p", { class: "onboard-brand", text: "SafePause" }),
          h("h1", { tabindex: "-1", text: "걱정되는 거래를 함께 알아차려요." }),
          h("p", { class: "muted", text: "내 거래에서 걱정되는 거래를 찾아 쉬운 말과 그림으로 알려 줘요." }),
          h("ul", { class: "promise" },
            h("li", null, icon("sparkle"), h("span", { text: "AI가 걱정되는 거래를 찾아요." })),
            h("li", null, icon("users"), h("span", { text: "조력자와 상담하는 곳에 알릴 수 있어요." })),
            h("li", null, icon("lock"), h("span", { text: `${where} 안에서만 살펴봐요.` })))),
        h("div", { class: "onboard-foot" },
          h("button", { type: "button", class: "btn primary big block", text: "다음", onclick: () => { step = 1; show(); } }),
          h("button", { type: "button", class: "btn ghost big block", text: "나중에 할게요", onclick: later })));
      } else if (step === 1) {
        const items = [
          ["monitoring", "chart", "거래 살펴보기", "내 거래를 살펴보고 걱정되는 거래를 찾아요."],
          ["helper_alerts", "users", "조력자에게 알리기", "꼭 확인할 거래가 생기면 내가 고른 조력자에게 알려요."],
          ["counseling_referral", "building", "상담하는 곳에 알려 주기", "꼭 확인할 일이 30일 동안 3번 이상 생기면 상담하는 곳에 알려 줘요."],
        ];
        fill(main, h("div", { class: "onboard-body" }, dots(), stepNo(),
          h("h1", { tabindex: "-1", text: "무엇을 해도 될까요?" }),
          h("p", { class: "muted onboard-sub", text: "하나씩 골라요. 처음에는 모두 꺼져 있어요. 언제든지 끌 수 있어요." }),
          h("div", { class: "list" }, items.map(([key, ic, title, desc]) => {
            const sw = h("button", { type: "button", class: "switch", role: "switch", "aria-checked": choice[key] ? "true" : "false", "aria-label": title,
              onclick: () => { choice[key] = !choice[key]; sw.setAttribute("aria-checked", choice[key] ? "true" : "false"); } });
            return h("div", { class: "switch-row consent-row" },
              h("div", { class: "consent-head" }, h("span", { class: "row-icon blue" }, icon(ic)), h("h3", { text: title }), sw),
              h("div", { class: "consent-body" }, h("p", { text: desc })));
          }))),
        h("div", { class: "onboard-foot" },
          h("button", { type: "button", class: "btn primary big block", text: "다음", onclick: () => { step = 2; show(); } }),
          h("button", { type: "button", class: "btn ghost big block", text: "이전으로", onclick: () => { step = 0; show(); } })));
      } else {
        const err = h("div");
        const radios = [["self", "나(본인)"], ["legal_representative", "법정대리인"]].map(([v, t]) => {
          const input = h("input", { type: "radio", name: "ob-given", value: v, checked: choice.given_by === v, onchange: () => { choice.given_by = v; } });
          return h("label", null, input, h("span", { text: t }));
        });
        fill(main, h("div", { class: "onboard-body" }, dots(), stepNo(),
          h("h1", { tabindex: "-1", text: "누가 동의했나요?" }),
          h("p", { class: "muted onboard-sub", text: "동의한 사람을 기록해요. 나중에 동의 화면에서 바꿀 수 있어요." }),
          h("div", { class: "segmented", role: "radiogroup", "aria-label": "누가 동의했나요?" }, radios),
          h("div", { class: "notice onboard-note" }, icon("lock"), h("p", { text: `기록은 ${where} 안에만 저장해요.` })),
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
          h("button", { type: "button", class: "btn ghost big block", text: "이전으로", onclick: () => { step = 1; show(); } })));
      }
      main.querySelector("h1")?.focus();
      fitFoot();
    }

    // 큰 글씨·가로 화면에서 아래 버튼 묶음이 화면의 1/3보다 크면 붙박이를 풀어 글을 가리지 않게 한다
    function fitFoot() {
      const foot = main.querySelector(".onboard-foot");
      if (!foot) return;
      foot.classList.remove("foot-flow");
      foot.classList.toggle("foot-flow", foot.offsetHeight > window.innerHeight / 3);
    }
    window.addEventListener("resize", fitFoot);
    ctx.onCleanup(() => window.removeEventListener("resize", fitFoot));
    show();
  },
};
