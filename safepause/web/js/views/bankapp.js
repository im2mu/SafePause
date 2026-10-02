/* 내 은행 앱: 휴대폰에 설치된 앱 목록에서 본인이 한 번 고르고(이 기기에만 기억), 돈 보내기 결과에서 그 앱을 연다.
 * - 은행 이름·로고는 앱에 넣지 않는다. 앱 이름에 은행·뱅크·bank·페이·pay·증권·카드가 들어간 앱을 위로 올릴 뿐이다.
 * - 고른 앱은 localStorage safepause.bankApp = {package, label}. 못 읽거나 못 써도 화면은 그대로 쓴다(try/catch).
 * - 앱 목록·열기는 안드로이드 앱에서만 된다(native.listApps·openApp). PC·휴대폰 브라우저는 버튼을 비활성으로 두고 까닭을 보인다.
 * - 다른 화면은 이 파일의 함수만 쓴다: bankAppActions(돈 보내기 결과), bankAppSettings(앱 설정), clearBankApp(모두 지우기).
 */
import { h, icon, fill, setText, openSheet, toast, announce } from "../ui.js";
import { canListApps, listApps, openApp, isApp } from "../native.js";

export const BANK_APP_KEY = "safepause.bankApp";
// 돈과 관련된 앱 이름에 흔히 들어가는 낱말(특정 회사 이름은 넣지 않는다)
const MONEY_WORDS = /은행|뱅크|bank|페이|pay|증권|카드/i;
const NO_CHECK = { spellcheck: "false", autocorrect: "off", autocapitalize: "off", autocomplete: "off" };

/** 은행 앱을 고를 수 없는 까닭(PC·브라우저·옛 앱). 고를 수 있으면 빈 글. */
export function bankAppUnavailable() {
  if (canListApps()) return "";
  return isApp() ? "이 앱 버전에서는 은행 앱을 열 수 없어요. 앱을 새 버전으로 바꿔 주세요." : "은행 앱은 휴대폰 앱에서 열 수 있어요.";
}

/** 고른 앱 {package, label} 또는 null. */
export function getBankApp() {
  try {
    const v = JSON.parse(localStorage.getItem(BANK_APP_KEY) || "null");
    if (v && typeof v.package === "string" && v.package && typeof v.label === "string") return { package: v.package, label: v.label || v.package };
  } catch (e) { /* 못 읽으면 고르지 않은 것으로 본다 */ }
  return null;
}

export function saveBankApp(app) {
  try { localStorage.setItem(BANK_APP_KEY, JSON.stringify({ package: app.package, label: app.label })); return true; } catch (e) { return false; }
}

/** 고른 은행 앱을 잊는다(설정의 지우기, 동의 화면의 모두 지우기). */
export function clearBankApp() {
  try { localStorage.removeItem(BANK_APP_KEY); } catch (e) { /* 무시 */ }
}

export function isMoneyApp(app) { return MONEY_WORDS.test(app.label || ""); }

const norm = (s) => String(s || "").toLowerCase().replace(/\s+/g, "");

/**
 * 내 은행 앱 고르기 시트. 검색 칸 + 돈 관련 앱 먼저 + 다른 앱.
 * 고르면 기억하고 Promise<{package, label}>, 닫으면 null.
 */
export function pickBankApp() {
  return new Promise((resolve) => {
    const why = bankAppUnavailable();
    if (why) { toast(why, "error"); resolve(null); return; }
    const apps = listApps();
    const current = getBankApp();
    let picked = null;
    const search = h("input", { class: "input", id: "ba-search", type: "search", maxlength: "40", enterkeyhint: "search", ...NO_CHECK, "aria-describedby": "ba-count" });
    const count = h("p", { class: "hint ba-count", id: "ba-count", "aria-live": "polite" });
    const listSlot = h("div", { class: "ba-list-slot" });

    openSheet((close) => {
      function row(app) {
        const on = Boolean(current && current.package === app.package);
        const money = isMoneyApp(app);
        return h("li", null, h("button", {
          type: "button", class: `row ba-app${on ? " on" : ""}`,
          onclick: () => {
            if (!saveBankApp(app)) toast("이 기기에 기억하지 못했어요. 이번에만 써요.", "error");
            picked = app;
            close();
          },
        },
        h("span", { class: `row-icon${money ? " blue" : ""}` }, icon(money ? "bank" : "grid")),
        h("span", { class: "row-main" }, h("span", { class: "row-title", text: app.label })),
        on ? h("span", { class: "badge info" }, icon("check-line"), h("span", { text: "지금 고른 앱" })) : null));
      }
      function group(title, list) {
        if (!list.length) return null;
        return h("section", { class: "ba-group", "aria-label": title },
          h("h3", { class: "ba-group-title", text: `${title} ${list.length}개` }),
          h("ul", { class: "list ba-list" }, list.map(row)));
      }
      function paint() {
        const q = norm(search.value);
        const hits = q ? apps.filter((a) => norm(a.label).includes(q)) : apps;
        const money = hits.filter(isMoneyApp);
        const others = hits.filter((a) => !isMoneyApp(a));
        count.textContent = q ? `찾은 앱 ${hits.length}개` : `이 휴대폰의 앱 ${apps.length}개`;
        if (!hits.length) {
          fill(listSlot, h("p", { class: "ba-empty", text: apps.length ? "찾는 앱이 없어요. 다른 이름으로 찾아 보세요." : "고를 수 있는 앱이 없어요." }));
          return;
        }
        fill(listSlot, group("돈 관련 앱", money), group(money.length ? "다른 앱" : "앱", others));
      }
      search.addEventListener("input", paint);
      paint();
      return [
        h("h2", { class: "sheet-title focus-target", tabindex: "-1", text: "내 은행 앱 고르기" }),
        h("p", { class: "sheet-sub", text: "내가 쓰는 은행 앱을 골라 주세요. 한 번 고르면 기억해요." }),
        h("div", { class: "field ba-search" }, h("label", { for: "ba-search", text: "앱 이름으로 찾기" }), search, count),
        listSlot,
        h("div", { class: "sheet-actions" }, h("button", { type: "button", class: "btn big block", text: "닫기", onclick: () => close() })),
      ];
    }, { label: "내 은행 앱 고르기", className: "ba-sheet", onClose: () => resolve(picked) });
  });
}

/** 고른 은행 앱을 연다. 열었으면 true. 못 열면 false(화면은 다시 고르게 한다). */
export function openBankApp(app = getBankApp()) {
  return Boolean(app && openApp(app.package));
}

/**
 * 돈 보내기 결과의 버튼 묶음: [내 은행 앱 열기](고른 앱 이름) / [다른 은행 앱 고르기].
 * 아직 고르지 않았으면 [내 은행 앱 고르기]. PC·브라우저면 비활성 버튼 + 까닭.
 */
export function bankAppActions() {
  const box = h("div", { class: "ba-actions" });
  const fail = h("div", { class: "ba-fail", role: "alert" });

  function openBtn(app, disabled) {
    return h("button", { type: "button", class: "btn primary big block ba-open", disabled, onclick: () => {
      fail.replaceChildren();
      if (openBankApp(app)) { toast(`${app.label} 앱을 열었어요.`); return; }
      fill(fail, h("div", { class: "notice red" }, icon("warning"), h("p", { text: "은행 앱을 열지 못했어요. 다시 골라 주세요." })));
      const again = box.querySelector(".ba-pick");
      if (again) again.focus();
    } }, icon("bank"), h("span", { class: "ba-open-text" },
      h("span", { text: "내 은행 앱 열기" }),
      app ? h("span", { class: "ba-open-name", text: app.label }) : null));
  }

  async function choose() {
    const app = await pickBankApp();
    if (!box.isConnected) return;
    paint();
    if (app) {
      announce(`${app.label} 앱을 골랐어요. 내 은행 앱 열기를 눌러 주세요.`);
      const btn = box.querySelector(".ba-open");
      if (btn) btn.focus();
    }
  }

  function paint() {
    const why = bankAppUnavailable();
    const app = getBankApp();
    fail.replaceChildren();
    if (why) {
      fill(box, openBtn(app, true), h("div", { class: "ba-why" }, icon("info"), h("p", { text: why })));
      return;
    }
    if (!app) {
      fill(box, fail,
        h("button", { type: "button", class: "btn primary big block ba-pick", onclick: choose }, icon("bank"), h("span", { text: "내 은행 앱 고르기" })),
        h("div", { class: "ba-why" }, icon("info"), h("p", { text: "한 번 고르면 다음부터 바로 열 수 있어요." })));
      return;
    }
    fill(box, fail, openBtn(app, false),
      h("button", { type: "button", class: "btn weak big block ba-pick", onclick: choose }, icon("refresh"), h("span", { text: "다른 은행 앱 고르기" })));
  }
  paint();
  return box;
}

/** 앱 설정의 내 은행 앱 줄: 고른 앱 이름 + [고르기]·[바꾸기]·[지우기]. */
export function bankAppSettings() {
  const card = h("div", { class: "card ba-settings" });
  function paint() {
    const app = getBankApp();
    const why = bankAppUnavailable();
    const name = h("p", { class: "ba-set-name" });
    setText(name, app ? app.label : "아직 고르지 않았어요.");
    fill(card,
      h("div", { class: "ba-set-head" },
        h("span", { class: "row-icon blue" }, icon("bank")),
        h("div", { class: "ba-set-main" }, h("h3", { text: "내 은행 앱" }), name)),
      h("p", { class: "muted", text: "돈 보내기에서 확인한 뒤 이 앱을 열어요. 보내기는 이 앱에서 해요." }),
      why ? h("div", { class: "ba-why" }, icon("info"), h("p", { text: why })) : null,
      h("div", { class: "btn-row ba-set-btns" },
        h("button", { type: "button", class: "btn weak", disabled: Boolean(why), onclick: async () => {
          const picked = await pickBankApp();
          if (!card.isConnected) return;
          paint();
          if (picked) { toast(`내 은행 앱: ${picked.label}`); card.querySelector(".ba-set-btns .btn").focus(); }
        } }, icon(app ? "refresh" : "plus"), h("span", { text: app ? "바꾸기" : "고르기" })),
        app ? h("button", { type: "button", class: "btn", onclick: () => {
          clearBankApp();
          paint();
          toast("내 은행 앱을 지웠어요.");
          card.querySelector(".ba-set-btns .btn").focus();
        } }, icon("trash"), h("span", { text: "지우기" })) : null));
  }
  paint();
  return card;
}
