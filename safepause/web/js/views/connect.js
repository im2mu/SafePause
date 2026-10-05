/* 은행 거래내역·카드 결제내역·휴대폰 결제내역 불러오기(준비 중) 시트. 내 거래와 전체 탭이 같이 쓴다.
 * 정식 버전에서 연결할 때의 순서를 비활성 단계로 보여 주기만 하고(동작하는 척하지 않음),
 * 지금 쓸 수 있는 방법(파일 올리기·연습용 거래)으로 안내한다.
 * - 은행·카드: 마이데이터로 연결한다. 단계는 고르기 → 본인 확인(인증서) → 가져올 기간 → 정보 보내기 동의 → 연결 완료(IA-3).
 * - 휴대폰 결제(소액결제·휴대폰 요금): 통신사에 연결하는 자리(AUG-11). 신호 5개 가운데 2개(휴대폰 소액결제 급증·휴대폰 요금 여러 회선)는
 *   이 내역이 있어야 찾을 수 있다. 어떤 제도·경로로 연결할지는 정하지 않았으므로 제도 이름을 쓰지 않는다.
 * 실제 은행·카드사·통신사 이름·로고는 쓰지 않는다(제휴로 오해받지 않게).
 */
import { h, icon, comingSoonSheet } from "../ui.js";

const PERIODS = ["3개월", "6개월", "12개월"];

/** 지금 쓸 수 있는 방법. opts.onUpload·onSample이 있으면 그것을, 없으면 내 거래 화면에서 그 시트를 연다.
 * 안내 글의 버튼 이름(파일 올리기·연습용 거래)은 줄을 바꾸지 않는 빈칸(\u00a0)으로 이어 버튼 이름과 같은 덩어리로 읽히게 한다
 * (연습용 / 거래로처럼 갈리지 않게, 덩어리는 6글자까지라 아주 큰 글씨 좁은 칸에도 든다) */
function nowOptions(ctx, opts) {
  return (close) => h("div", { class: "soon-now" },
    // 끝 말은 짧게(해 보세요): 해 볼 수 있어요는 한 덩어리(6글자)라 큰 글씨에서 앞 낱말(거래로)만 한 줄에 홀로 남았다(360폭 2배).
    // 버튼 이름과 같은 구(파일 올리기·연습용 거래)는 줄을 바꾸지 않는 빈칸으로 잇는다
    h("p", { class: "soon-now-title", text: "지금은 파일\u00a0올리기나 연습용\u00a0거래로 해 보세요." }),
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

/** 고른 뒤 공통 단계: 가져올 기간 → 정보 보내기 동의 → 연결 완료. done은 연결 완료 단계의 설명 한 줄.
 * 설명의 얼마 동안은 줄을 바꾸지 않는 빈칸(\u00a0)으로 잇는다(어떤 정보를 얼마 / 동안처럼 갈리지 않게). */
function laterSteps(done) {
  return [
    { title: "가져올 기간", options: PERIODS },
    { title: "정보 보내기 동의", sub: "어떤 정보를 얼마\u00a0동안 가져올지 확인하고 동의해요." },
    { title: "연결 완료", sub: done },
  ];
}

/** 은행 거래내역 불러오기(준비 중). opts: {onUpload, onSample} */
export function openBankConnect(ctx, opts = {}) {
  return comingSoonSheet({
    icon: "bank",
    title: "은행 거래내역 불러오기",
    lines: ["마이데이터로 내 계좌를 연결해요.", "연결하면 거래내역을 자동으로 불러와요."],
    steps: [
      { title: "은행 고르기", sub: "내 계좌가 있는 은행을 골라요." },
      { title: "본인 확인", sub: "인증서로 내가 맞는지 확인해요." },
      ...laterSteps("불러온 계좌를 확인해요."),
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
      { title: "본인 확인", sub: "인증서로 내가 맞는지 확인해요." },
      ...laterSteps("불러온 카드를 확인해요."),
    ],
    action: "연결하기",
    extra: nowOptions(ctx, opts),
  });
}

/** 휴대폰 결제내역 불러오기(준비 중, AUG-11): 휴대폰 소액결제·휴대폰 요금. opts: {onUpload, onSample} */
export function openPhonePayConnect(ctx, opts = {}) {
  return comingSoonSheet({
    icon: "sig-phone-pay",
    title: "휴대폰 결제내역 불러오기",
    lines: ["내 통신사에 연결해 휴대폰 결제와 휴대폰 요금 내역을 불러와요.",
      "휴대폰 결제가 갑자기 늘거나 요금이 여러 회선에서 나오는지 살펴볼 수 있어요."],
    steps: [
      { title: "통신사 고르기", sub: "내가 쓰는 통신사를 골라요." },
      { title: "본인 확인", sub: "휴대폰으로 내가 맞는지 확인해요." },
      ...laterSteps("불러온 결제내역을 확인해요."),
    ],
    action: "연결하기",
    extra: nowOptions(ctx, opts),
  });
}
