/* 은행 거래내역·카드 결제내역 불러오기(준비 중) 시트. 내 거래와 전체 탭이 같이 쓴다.
 * 정식 버전에서는 마이데이터로 계좌·카드를 연결한다. 지금은 단계를 비활성으로 보여 주기만 하고(동작하는 척하지 않음),
 * 지금 쓸 수 있는 방법(파일 올리기·연습용 거래)으로 안내한다.
 * 실제 은행·카드사 이름·로고는 쓰지 않는다(제휴로 오해받지 않게).
 */
import { h, icon, comingSoonSheet } from "../ui.js";

const PERIODS = ["3개월", "6개월", "12개월"];

/** 지금 쓸 수 있는 방법. opts.onUpload·onSample이 있으면 그것을, 없으면 내 거래 화면에서 그 시트를 연다. */
function nowOptions(ctx, opts) {
  return (close) => h("div", { class: "soon-now" },
    h("p", { class: "soon-now-title", text: "지금은 파일 올리기나 연습용 거래로 해 볼 수 있어요." }),
    h("div", { class: "btn-row" },
      h("button", { type: "button", class: "btn weak", onclick: () => { close(); run(ctx, opts.onUpload, "upload"); } },
        icon("upload"), h("span", { text: "파일 올리기" })),
      h("button", { type: "button", class: "btn weak", onclick: () => { close(); run(ctx, opts.onSample, "sample"); } },
        icon("sparkle"), h("span", { text: "연습용 거래 불러오기" }))));
}

function run(ctx, fn, open) {
  if (typeof fn === "function") { fn(); return; }
  ctx.go(`txns?open=${open}`);   // 내 거래 화면이 params.open을 보고 시트를 연다
}

/** 은행 거래내역 불러오기(준비 중). opts: {onUpload, onSample} */
export function openBankConnect(ctx, opts = {}) {
  return comingSoonSheet({
    icon: "bank",
    title: "은행 거래내역 불러오기",
    lines: ["마이데이터로 내 계좌를 연결해요.", "연결하면 거래내역을 자동으로 불러와요."],
    steps: [
      { title: "은행 고르기", sub: "내 계좌가 있는 은행을 골라요." },
      { title: "본인 확인", sub: "휴대폰으로 내가 맞는지 확인해요." },
      { title: "가져올 기간", options: PERIODS },
    ],
    action: "연결하기",
    extra: nowOptions(ctx, opts),
  });
}

/** 카드 결제내역 불러오기(준비 중). opts: {onUpload, onSample} */
export function openCardConnect(ctx, opts = {}) {
  return comingSoonSheet({
    icon: "card",
    title: "카드 결제내역 불러오기",
    lines: ["마이데이터로 내 카드를 연결해요.", "연결하면 카드 결제내역을 자동으로 불러와요."],
    steps: [
      { title: "카드사 고르기", sub: "내가 쓰는 카드사를 골라요." },
      { title: "본인 확인", sub: "휴대폰으로 내가 맞는지 확인해요." },
      { title: "가져올 기간", options: PERIODS },
    ],
    action: "연결하기",
    extra: nowOptions(ctx, opts),
  });
}
