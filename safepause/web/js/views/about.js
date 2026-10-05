/* AI와 데이터 설명(조력자·기관용): 판단 방법, 학습 데이터셋 요약, 한계, 오픈소스 고지.
 * 공고 선택 사항(AI 모델 코드·설명, 학습 데이터셋 요약)을 앱 안에서도 볼 수 있게 한 화면이다.
 * 내용 근거: docs/model_card.md, docs/dataset_card.md, safepause/detect/engine.py(결합 규칙). 수치는 바꾸지 않는다.
 * 목록 안 설명도 문장마다 한 줄(li 안에 p, C6). 앱이 하는 일보다 크게 말하지 않는다(C10·C11·C13). */
import { h, icon, fill } from "../ui.js";
import { SIGNAL_KO, SIGNAL_ICON, SIGNALS } from "../labels.js";
import { deviceWord } from "../format.js";
import { capabilities } from "../native.js";
import { MODE } from "../api.js";

// 목록 한 줄(문장이 둘이면 줄을 나눔)
const li = (text) => h("li", null, h("p", { text }));
// 번호 제목(② 나만의 평소 기준 AI): 번호는 왼쪽 칸, 제목은 옆 칸에서 줄을 바꾼다(번호만 첫 줄에 홀로 남지 않게)
const stepTitle = (t) => { const [no, ...rest] = t.split(" "); return h("h3", { class: "step-title" }, h("span", { class: "step-no", text: no }), h("span", { text: rest.join(" ") })); };

const RULES = {
  night_repeat_transfer: "밤 11시~새벽 6시에 이체가 7일 안에 2건이면 확인, 3건이면 꼭 확인",
  payee_surge: "한 상대에게 7일 동안 보낸 돈이 내 평소보다 크게 많을 때",
  micropay_surge: "7일 동안 휴대폰 소액결제 건수·금액이 평소보다 크게 많을 때",
  new_merchant_high_value: "처음 가는 가게에서 내 평소보다 큰 돈을 낼 때",
  multi_line_telecom: "짧은 기간에 처음 보는 회선의 통신요금이 여러 개 나올 때",
};

export default {
  title: "AI와 데이터 설명",
  back: "more",
  tab: "more",
  async render(ctx) {
    const where = deviceWord();
    const apps = capabilities().sms ? "문자·메일 앱" : "메일 앱";
    fill(ctx.main,
      h("h2", { class: "page-title", tabindex: "-1", text: "AI와 데이터 설명" }),
      h("p", { class: "page-sub", text: "SafePause가 어떻게 판단하고, 무엇으로 배웠는지 적었어요." }),

      h("h3", { class: "section-title", text: "어떻게 판단하나요" }),
      h("div", { class: "list" },
        h("div", { class: "list-head step-title" }, h("span", { class: "step-no", text: "①" }), h("span", { text: "약속(규칙) 5가지: 착취 때 자주 보이는 다섯\u00a0가지 모습" })),
        SIGNALS.map((code) => h("div", { class: "row" }, h("span", { class: "row-icon orange" }, icon(SIGNAL_ICON[code])),
          h("span", { class: "row-main" }, h("span", { class: "row-title about-wrap", text: SIGNAL_KO[code] }),
            h("span", { class: "row-sub about-wrap", text: RULES[code] }))))),
      h("div", { class: "card" },
        stepTitle("② 나만의 평소 기준 AI"),
        h("p", { text: "내 과거 거래로 Isolation Forest(이상 탐지 모델)를 배워요. 금액·시간대·처음 보는 상대·7일 건수 등 11가지 특징을 봐요." }),
        h("p", { class: "muted", text: "점수는 내 평소 거래 가운데 이 거래보다 덜 특이한 비율(0~1)이에요." })),
      h("div", { class: "card" },
        stepTitle("③ 둘을 합치는 방법"),
        h("ul", { class: "bullets about-bullets" },
          li("약속으로 꼭 확인할 거래면 그대로 꼭 확인이에요."),
          li("약속으로 확인할 거래이고 AI 점수가 0.90 이상이면 꼭 확인으로 올려요."),
          li("약속에 걸리지 않은 나가는 돈은 AI 점수가 0.98 이상일 때만 확인이에요. 꼭 확인까지는 안 올려요."),
          li("거래가 30건보다 적으면 AI 없이 약속으로만 봐요."))),
      h("div", { class: "card" },
        stepTitle("④ 돈 보내기 전 확인"),
        h("ul", { class: "bullets about-bullets" },
          li("돈 보내기에서 적은 받는 사람과 금액도 위와 같은 방법으로 살펴봐요."),
          li("거래가 30건보다 적으면 AI 없이 약속으로만 살펴봐요."),
          li("거래 살펴보기 동의를 끄면 안 살펴봐요."))),

      h("h3", { class: "section-title", text: "무엇으로 배웠나요 (학습 데이터셋 요약)" }),
      h("div", { class: "card" },
        // 첫 문단: 무엇으로 만들었나(첫 문장은 굵게) / 둘째 문단: 앱을 쓸 때는 무엇으로 배우나
        h("p", { class: "lead-strong", text: "개발·평가에는 실제 사람의 거래를 쓰지 않았어요. 착취 때 자주 보이는 다섯\u00a0가지 모습을 재현하도록 만든 합성(가상) 데이터예요." }),
        h("p", { class: "muted", text: "앱을 쓸 때는 내가 올린 내 거래로 내 평소 모습을 배워요(위 ②)." }),
        h("ul", { class: "bullets about-bullets" },
          li("가상 인물 3종: 근로자(월급), 복지급여 수급자, 학생(용돈)"),
          li("한 사례는 120일 거래예요. 앞 90일(정상 거래)로 배우고, 뒤 30일을 확인해요."),
          li("걱정되는 거래 5종을 마지막 30일 안에 1번씩 섞어요(정답 표시가 붙음)."),
          li("평가는 인물 3명마다 번호(seed) 20개씩, 모두 60사례예요. 약속을 다듬은 1~20과 다른 21~40으로 따로 확인했어요."),
          li("처음 가는 가게·밤 결제·처음 보는 상대 소액 송금 같은 평범한 잡음도 넣어 잘못 알리는 정도를 재요.")),
        h("p", { class: "muted about-gap", text: "인물 값은 공개 통계로 보정하지 않은 가정이에요. 그래서 실제 탐지 성능을 뜻하지 않아요." })),

      h("h3", { class: "section-title", text: "아직 못 한 것 (한계)" }),
      h("div", { class: "notice orange" }, icon("warning"), h("ul", null,
        li("실제 사용자와 현장에서는 아직 검증하지 않았어요."),
        li("은행·카드 마이데이터 연결은 정식 버전에서 할 일이에요. 인터넷 연결과 허가가 필요해요."),
        li("현금을 찾게 하는 일과 늘 가던 가게에서 내 카드를 대신 쓰는 일은 아직 따로 정한 약속(규칙)이 없어요. AI가 평소와 아주 다르다고 볼 때만 확인으로 알릴 수 있어요."),
        li("쉬운 말 문장은 발달장애 당사자의 감수를 아직 받지 않았어요."),
        li("은행마다 다른 파일 모양은 모두 시험하지 못했어요."))),

      h("h3", { class: "section-title", text: "개인정보" }),
      // 문단: 어디서 판단하고 무엇이 밖으로 가나 / 무엇을 어디에 남기나 / 지우기
      h("div", { class: "notice blue" }, icon("lock"), h("div", null,
        h("p", { text: [MODE === "engine"
          ? `이 앱은 인터넷 권한을 요청하지 않아요. 판단은 모두 ${where} 안의 파이썬 AI 엔진이 해요.`
          : `SafePause는 ${where} 안에서만 열려요. 분석은 모두 ${where} 안에서 해요.`,
        `알림 보내기에서 내가 보내는 글만 ${apps}으로 넘어가요.`].join(" ") }),
        h("p", { text: [MODE === "engine" ? "앱 데이터는 휴대폰 백업이나 새 휴대폰으로 옮길 때 함께 가지 않아요." : "",
          "조력자의 번호·메일은 문자·메일 앱을 열 때만 써요. 알림 기록과 내보내는 파일에는 넣지 않아요."].filter(Boolean).join(" ") }),
        h("p", { text: "동의 화면 맨 아래에서 언제든지 모두 지울 수 있어요." }))),

      h("h3", { class: "section-title", text: "오픈소스 고지" }),
      h("div", { class: "card" },
        h("p", { class: "muted", text: "SafePause는 아래 오픈소스를 써요. 각 라이선스 전문은 앱과 함께 담긴 licenses 폴더에 있어요." }),
        h("ul", { class: "bullets about-bullets" },
          ["Pyodide (MPL-2.0)", "Python 표준 라이브러리 (PSF License)", "NumPy (BSD-3-Clause)", "SciPy (BSD-3-Clause)",
            "scikit-learn (BSD-3-Clause)", "joblib (BSD-3-Clause)", "threadpoolctl (BSD-3-Clause)", "pydantic, pydantic-core (MIT)",
            "typing-extensions (PSF License)", "annotated-types, typing-inspection (MIT)"].map((t) => {
            // threadpool·ctl 사이 줄 바꿀 자리(wbr): 아주 큰 글씨 좁은 화면에서 threadpoolct / l로 잘리지 않게. 연성 붙임표(\u00ad)는
            // Chrome·WebView가 줄이 바뀌지 않아도 붙임표로 그려 이름이 threadpool-ctl로 보였다
            if (t.startsWith("threadpoolctl ")) return h("li", null, h("span", { text: "threadpool" }), h("wbr"), h("span", { text: t.slice(10) }));
            // 빈칸이 든 괄호 라이선스 이름((PSF License))은 한 덩어리(inline-block: 들어가면 한 줄, 칸보다 넓으면 안에서 줄바꿈)로
            // (PSF / License)처럼 갈리지 않게. 빈칸 없는 이름((BSD-3-Clause))은 글 넣기의 낱말 묶기가 이미 덩어리로 만든다
            const m = /^(.*) (\([^()]* [^()]*\))$/.exec(t);
            return m ? h("li", null, h("span", { text: m[1] }), " ", h("span", { class: "keep-word", text: m[2] })) : h("li", { text: t });
          }),
          MODE === "engine" ? null : ["FastAPI, Starlette, Uvicorn (BSD/MIT)"].map((t) => h("li", { text: t })))),
      h("p", { class: "muted center more-foot", text: "SafePause 0.3.0" }));
  },
};
