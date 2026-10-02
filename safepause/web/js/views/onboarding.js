/* 처음 켰을 때: 무엇을 하는 앱인지 → 동의 세 가지(모두 꺼짐에서 시작, 따로 고름) → 누가 동의했는지 + 약관 동의 자리.
 * 약관·개인정보 수집·이용 동의는 정식 버전에서 필수가 된다. 지금은 준비 중 자리만 두고 시작을 막지 않는다(IA-6).
 * 1단계 소개는 전체 탭의 사용법 안내(guide.js)가 introNodes로 다시 보여 준다(J10). */
import { h, icon, fill, busy, toast, paragraphs } from "../ui.js";
import { errorNotice, menuRow } from "../components.js";
import { deviceWord } from "../format.js";
import { STALE } from "../api.js";
import { openSoon } from "./more.js";

/** 1단계 소개(로고·한 줄 소개·약속 셋). 사용법 안내 화면도 같이 쓴다. heading: "h1"(첫 실행) 또는 "h2"(사용법 안내) */
export function introNodes(heading = "h1") {
  return [
    h("div", { class: "onboard-brandrow" },
      h("div", { class: "onboard-hero brand-mark" }, icon("logo")),
      h("p", { class: "onboard-brand", text: "SafePause" })),
    h(heading, { class: "onboard-title", tabindex: "-1", text: "걱정되는 거래를 함께 알아차려요." }),
    h("p", { class: "muted", text: "내 거래에서 걱정되는 거래를 찾아 쉬운 말과 그림으로 알려 줘요." }),
    h("ul", { class: "promise" },
      h("li", null, icon("sparkle"), h("span", { text: "AI가 걱정되는 거래를 찾아요." })),
      h("li", null, icon("users"), h("span", { text: "조력자와 상담하는 곳에 알릴 수 있어요." })),
      h("li", null, icon("lock"), h("span", { text: `${deviceWord()} 안에서만 살펴봐요.` }))),
  ];
}

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
        fill(main, h("div", { class: "onboard-body onboard-intro" }, dots(), stepNo(), introNodes("h1")),
        h("div", { class: "onboard-foot" },
          h("button", { type: "button", class: "btn primary big block", text: "다음", onclick: () => { step = 1; show(); } }),
          h("button", { type: "button", class: "btn ghost big block", text: "나중에 할게요", onclick: later })));
      } else if (step === 1) {
        // 설명은 동의 화면과 같은 뜻을 짧게(C2): 미리 골라 두고 적어 둘 뿐, 보내기는 본인이 누른다. 한 항목은 한 문단
        const items = [
          ["monitoring", "chart", "거래 살펴보기", ["내 거래를 살펴보고 걱정되는 거래를 찾아요."]],
          ["helper_alerts", "users", "조력자에게 알리기", ["걱정되는 거래를 알릴 때 조력자를 미리 골라 두고 적어 둬요.", "보내기는 내가 눌러요."]],
          ["counseling_referral", "building", "상담하는 곳에 알려 주기", ["상담하는 곳에 알려 줘요.", "알릴 때가 되면 상담하는 곳을 추천해요.", "보내기는 내가 눌러요."]],
        ];
        fill(main, h("div", { class: "onboard-body" }, dots(), stepNo(),
          h("h1", { tabindex: "-1", text: "무엇을 해도 될까요?" }),
          h("p", { class: "muted onboard-sub", text: "하나씩 골라요. 처음에는 모두 꺼져 있어요. 언제든지 끌 수 있어요." }),
          h("div", { class: "list" }, items.map(([key, ic, title, desc]) => {
            const sw = h("button", { type: "button", class: "switch", role: "switch", "aria-checked": choice[key] ? "true" : "false", "aria-label": title,
              onclick: () => { choice[key] = !choice[key]; sw.setAttribute("aria-checked", choice[key] ? "true" : "false"); } });
            return h("div", { class: "switch-row consent-row" },
              h("div", { class: "consent-head" }, h("span", { class: "row-icon blue" }, icon(ic)), h("h3", { text: title }), sw),
              h("div", { class: "consent-body" }, paragraphs(desc).map((t) => h("p", { text: t }))));
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
          // 약관 동의 자리(IA-6): 정식 버전에서 필수가 된다. 지금은 내용 보기만 준비 중 안내로 연다
          h("h2", { class: "section-title onboard-terms-title", text: "약관 동의" }),
          h("p", { class: "muted", text: "정식 버전에서는 시작하기 전에 읽고 동의해요. 지금은 동의하지 않아도 쓸 수 있어요." }),
          h("div", { class: "list onboard-terms" },
            menuRow({ icon: "doc", title: "이용약관 동의", sub: "정식 버전에서 꼭 필요해요.", soon: true, onclick: () => openSoon("terms") }),
            menuRow({ icon: "shield", title: "개인정보 수집·이용 동의", sub: "정식 버전에서 꼭 필요해요.", soon: true, onclick: () => openSoon("collect") })),
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
    // 글자 크기를 나중에 바꿔도(설정·기기 글자 크기) 버튼 묶음 높이가 바뀌면 다시 잰다
    if (typeof ResizeObserver === "function") {
      let lastH = 0;
      const ro = new ResizeObserver(() => {
        const foot = main.querySelector(".onboard-foot");
        if (foot && foot.offsetHeight !== lastH) { lastH = foot.offsetHeight; fitFoot(); }
      });
      ro.observe(main);
      ctx.onCleanup(() => ro.disconnect());
    }
    show();
  },
};
