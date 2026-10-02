/* 앱 설정: 글자 크기·화면 모드는 고르는 즉시 바뀌고 이 기기에 저장된다(ui.setPref → html[data-font]·[data-theme]).
 * 휴대폰 알림 받기·앱 잠금은 정식 버전 기능이라 준비 중 안내만 연다. */
import { h, icon, fill, toast, announce, comingSoonSheet, getPref, setPref } from "../ui.js";
import { menuRow } from "../components.js";
import { deviceWord } from "../format.js";

const FONTS = [
  { value: "m", label: "보통", cls: "fs-m" },
  { value: "l", label: "크게", cls: "fs-l" },
  { value: "xl", label: "아주 크게", cls: "fs-xl" },
];
const THEMES = [
  { value: "auto", label: "자동", icon: "moon-sun" },
  { value: "light", label: "밝게", icon: "sun" },
  { value: "dark", label: "어둡게", icon: "moon" },
];

export default {
  title: "앱 설정",
  back: "more",
  tab: "more",
  async render(ctx) {
    const font = radioGroup("pref-font", FONTS, getPref("font"), (opt) => h("span", { class: "pref-opt" },
      h("span", { class: `pref-sample ${opt.cls}`, "aria-hidden": "true", text: "가" }), h("span", { text: opt.label })), (v, opt) => {
      setPref("font", v);
      const msg = `글자 크기: ${opt.label}`;
      toast(msg);
      announce(msg);
    });
    const theme = radioGroup("pref-theme", THEMES, getPref("theme"), (opt) => h("span", { class: "pref-opt" },
      LINE[opt.icon] ? lineIcon(LINE[opt.icon]) : icon(opt.icon), h("span", { text: opt.label })), (v, opt) => {
      setPref("theme", v);
      const msg = `화면 모드: ${opt.label}`;
      toast(msg);
      announce(msg);
    });

    fill(ctx.main,
      h("h2", { class: "page-title", tabindex: "-1", text: "앱 설정" }),
      h("p", { class: "page-sub", text: `고르면 바로 바뀌어요. ${deviceWord()}에 저장해요.` }),

      h("h3", { class: "section-title", id: "pref-font-title" }, h("span", { class: "pref-head" }, icon("text-size"), h("span", { text: "글자 크기" }))),
      h("div", { class: "card pref-card" }, font,
        h("p", { class: "pref-preview", text: "이 크기로 글자가 보여요. 꼭 확인할 거래가 있어요." })),

      h("h3", { class: "section-title", id: "pref-theme-title" }, h("span", { class: "pref-head" }, icon("moon-sun"), h("span", { text: "화면 모드" }))),
      h("div", { class: "card pref-card" }, theme,
        h("p", { class: "muted", text: `자동은 ${deviceWord()} 설정을 따라요.` })),

      h("h3", { class: "section-title", text: "알림·보안" }),
      h("div", { class: "list" },
        menuRow({ icon: "bell", title: "휴대폰 알림 받기", soon: true, onclick: () => comingSoonSheet({
          icon: "bell", title: "휴대폰 알림 받기",
          lines: ["꼭 확인할 거래가 생기면 휴대폰 알림으로 알려 줘요.", "알림을 누르면 그 거래 카드가 바로 열려요."], action: "켜기" }) }),
        menuRow({ icon: "lock", title: "앱 잠금", soon: true, onclick: () => comingSoonSheet({
          icon: "lock", title: "앱 잠금",
          lines: ["앱을 열 때 잠금을 풀어야 열려요.", "지문이나 비밀번호로 열 수 있어요."], action: "켜기" }) })));
  },
};

// 라디오 묶음(공용 .segmented). 고르는 즉시 onPick을 부른다
function radioGroup(name, options, current, render, onPick) {
  return h("div", { class: "segmented pref-seg", role: "radiogroup", "aria-labelledby": `${name}-title` },
    options.map((opt) => h("label", null,
      h("input", { type: "radio", name, value: opt.value, checked: opt.value === current, onchange: (e) => { if (e.target.checked) onPick(opt.value, opt); } }),
      render(opt))));
}

// 밝게·어둡게 선 아이콘(공용 UI 아이콘에 없어 여기서 그린다, 24 viewBox·선 굵기 2·둥근 끝)
const LINE = {
  sun: [["circle", { cx: "12", cy: "12", r: "4" }],
    ...["M12 2v2", "M12 20v2", "M4.9 4.9l1.4 1.4", "M17.7 17.7l1.4 1.4", "M2 12h2", "M20 12h2", "M4.9 19.1l1.4-1.4", "M17.7 6.3l1.4-1.4"].map((d) => ["path", { d }])],
  moon: [["path", { d: "M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5a8.5 8.5 0 1 0 11 11Z" }]],
};

function lineIcon(parts) {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  for (const [k, v] of Object.entries({ viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "2",
    "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", focusable: "false" })) svg.setAttribute(k, v);
  for (const [tag, attrs] of parts) {
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    svg.append(el);
  }
  return svg;
}
