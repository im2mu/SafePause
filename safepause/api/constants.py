"""서비스 계층이 쓰는 가벼운 상수.

앱(안드로이드)은 AI 패키지(numpy·scipy·scikit-learn)를 뒤에서 싣는 동안에도 동의·조력자 화면을 먼저 쓸 수
있어야 한다. 그래서 이 모듈과 service의 맨 위 import는 numpy를 싣지 않는다. 아래 값은 원래 모듈
(synth·anomaly)의 값과 같아야 하며, tests/test_api_service.py가 같은지 검사한다.
"""
from __future__ import annotations

MIN_YEAR, MAX_YEAR = 1900, 2100            # = synth.MIN_YEAR, synth.MAX_YEAR
NORMAL_LABEL = "normal"                     # = synth.NORMAL_LABEL
SCENARIO_WINDOW_DAYS = 30                   # = synth.SCENARIO_WINDOW_DAYS
PERSONA_KEYS: tuple[str, ...] = ("worker", "benefit", "student")   # = tuple(synth.PERSONAS)
MIN_TRAIN = 30                              # = detect.anomaly.MIN_TRAIN

TRAIN_RATIO = 0.75                          # 저장된 거래 앞 75%로 학습(최소 MIN_TRAIN건)
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_MAPPING_CHARS = 4096                    # 열 이름 지정(JSON) 길이 한도(깊게 중첩된 JSON으로 인한 오류 방지)
MAX_HELPERS = 10
MAX_EVAL_SEEDS = 20                         # 직접 다시 계산: seed 개수 최대(보고서 검증 세트와 같은 20개)
MAX_EVAL_SEED_START = 10_000                # 직접 다시 계산: 시작 seed 최대
EVAL_INTENSITIES: tuple[str, ...] = ("standard", "subtle")   # = synth.INTENSITIES (표준·경계 변형)
# 제출 보고서 검증 세트(docs/eval/eval_results_holdout.json·eval_results_subtle_holdout.json, 화면 eval_reference.json):
# 인물 3명 × seed 21~40. 직접 다시 계산이 이 설정과 같은지(report_set)를 알려 주는 데 쓴다
REPORT_SEED_START, REPORT_SEEDS = 21, 20
LIVE_ID_PREFIX = "live-"                    # 보내기 전 확인(check/decide)으로 더한 거래 id
LIVE_ID_DIGITS = 9                          # live-000000001 ~ live-999999999
MAX_REMEMBERED_LIVE_IDS = 1000              # check가 준 확인 거래 id를 이만큼 기억한다(오래된 것부터 잊음)
# 보내기 전 확인으로 더한 거래의 메모(내 거래 시트에 보임). v0.3: 연습이라는 말을 쓰지 않는다(이름은 호환용으로 그대로)
PRACTICE_MEMO = "보내기 전 확인"
LEGACY_PRACTICE_MEMOS = ("안전 정지 연습",)    # v0.2가 적은 메모. 저장은 그대로 두고 화면에 줄 때만 PRACTICE_MEMO로 보인다
MIN_MONTHLY_DAYS = 14                       # 이보다 짧은 기간은 '한 달 평균'으로 늘려 말하지 않는다

# v0.2 연습 화면 안내. 평가·옛 호환을 위해 상수만 남기고, v0.3 응답(check/decide의 practice_note)에는 넣지 않는다(빈 글)
PRACTICE_NOTE = "연습 화면이에요. 실제로 돈이 나가지 않아요."
# 확인한 거래의 날짜(v0.3 수정 계획 A): 저장된 실제 거래의 마지막 시각이 이 날수 안이면 오늘 날짜(실사용),
# 더 오래됐으면(합성·옛 데이터) 마지막 실제 거래 날짜에 고른 시각을 붙인다(데모). 확인을 여러 번 해도 날짜를 밀지 않는다
LIVE_RECENT_DAYS = 45
TS_NOTE = ("저장된 거래가 오래전 것이라 확인한 거래는 저장된 거래 끝에 이어서 적어요. "
           "그래서 날짜가 오늘과 달라요. 시각만 고른 대로예요.")
LIVE_IDS_USED_UP = "보내기 전 확인 번호를 다 썼어요. 동의 화면에서 모두 지운 뒤 다시 해 주세요."
TOO_BIG = "파일이 너무 커요(5MB까지)."
NO_MONITORING = ("거래 살펴보기에 동의하지 않아서 분석하지 않았어요. "
                 "동의 화면에서 거래 살펴보기를 켜 주세요.")
SUPERSEDED = ("지우기(또는 동의 끄기)가 먼저 처리돼서 이번 거래는 저장하지 않았어요. "
              "필요하면 다시 해 주세요.")
NO_FILE = "올린 파일을 찾지 못했어요. CSV나 엑셀(.xlsx) 파일을 골라 다시 올려 주세요."
SYNTHETIC_NOTE = "합성 데이터 기준, 실제 피해 데이터 검증 아님"
LABELED_NOTE = ("지금 저장된 거래에는 연습용으로 섞은 걱정되는 거래가 있어요. "
                "이 숫자는 잘못 알린 비율이 아니에요.")

# ---- v0.3: 상담하는 곳·담은 거래·보낸 알림 ----
MAX_COUNSELORS = 20
COUNSELOR_KINDS: tuple[str, ...] = ("disability_center", "rights_agency", "police", "finance", "other")
# 추천 상담하는 곳(확인된 번호만). 출처
# - 장애인권익옹호기관 1644-8295: 중앙장애인권익옹호기관 naapd.or.kr/abuse/report(전국 공통, 전화·문자·카카오톡)
#   괄호 안은 학대 신고(기관 이름에 장애인이 있다): 장애인학대 신고는 큰 글씨 좁은 칸에서 (장애인학대 / 신고)로 꼬리 줄이 생겼다
# - 금융감독원 1332: 금융감독원 fss.or.kr 서민금융1332
# - 경찰 112: 국번 없이
# - 지역발달장애인지원센터: 지역마다 번호가 달라 비워 둔다(사용자가 적음)
COUNSELOR_PRESETS: tuple[dict[str, str], ...] = (
    {"kind": "rights_agency", "name": "장애인권익옹호기관 (학대 신고)", "phone": "1644-8295", "email": "",
     "memo": "전국 같은 번호예요. 전화·문자·카카오톡으로 알릴 수 있어요."},
    {"kind": "finance", "name": "금융감독원 불법금융 신고", "phone": "1332", "email": "",
     "memo": "돈 문제로 속은 것 같으면 상담할 수 있어요."},
    {"kind": "police", "name": "경찰 (금융사기 신고)", "phone": "112", "email": "",
     "memo": "국번 없이 112예요."},
    {"kind": "disability_center", "name": "지역발달장애인지원센터", "phone": "", "email": "",
     "memo": "지역마다 번호가 달라요. 우리 지역 센터 번호를 적어 주세요."},
)
NOTICE_CHANNELS: tuple[str, ...] = ("sms", "email", "call", "copy")
MAX_NOTICE_RECIPIENTS = 10
MAX_NOTICE_TXNS = 20
MAX_NOTICE_MESSAGE = 1000
MAX_TXN_ID_CHARS = 200                      # 담기·알림 기록에서 받는 거래 id 길이 한도(표준 CSV id는 파일 그대로라 넉넉히)
NOTICES_NOTE = "이 기기에 적어 둔 기록이에요. 실제로 보냈는지는 문자·메일 앱에서 확인해 주세요."
TXN_NOT_FOUND = "그 거래를 찾지 못했어요."
CONFLICT_REASON = "이 거래에서 돈을 받은 사람이에요."   # 받는 사람 추천: 거래 상대방인 조력자
INSIGHT_MONTHS = 6                          # 돈 흐름 분석: 최근 몇 달까지 보여 줄지
TOP_PAYEES = 3

# ---- v0.3 수정 계획(docs/v03_fixplan.md) ----
# 연습용 거래 기본 조합: AI만 먼저 잡은 거래(규칙 신호 없이 AI가 걱정한 거래)가 1건 이상 나오는 조합(테스트로 고정)
DEFAULT_SAMPLE_PERSONA = "worker"
DEFAULT_SAMPLE_SEED = 10                     # 근로자·번호 10: 김*호 첫 새벽 이체(28만 원)를 AI만 먼저 잡고, 다음 이체부터 규칙도 잡는다
REVIEW_OK = "ok"                            # 내가 한 거예요(오탐 바로잡기) 표시. 탐지 등급은 바꾸지 않는다
NOTICE_NOT_FOUND = "그 알림 기록을 찾지 못했어요."
ONLY_CHECKED = "보내기 전 확인 기록만 지울 수 있어요."
UPLOAD_MODES: tuple[str, ...] = ("replace", "append")   # 파일 올리기: 모두 바꾸기 / 이어 붙이기(같은 거래는 한 번만)
# 화면 이름표(web/js/labels.js CHANNEL_KO·SIGNAL_KO와 같은 글). 분석 결과 표 파일(CSV)에 쓴다
CHANNEL_KO: dict[str, str] = {
    "transfer": "계좌 이체", "card": "카드 결제", "micropay": "휴대폰 결제", "telecom_bill": "휴대폰 요금",
    "atm": "현금 찾기", "income": "들어온 돈", "other": "기타",
}
SIGNAL_KO: dict[str, str] = {
    "night_repeat_transfer": "밤 시간 잦은 이체",
    "payee_surge": "한 사람에게 송금 집중",
    "micropay_surge": "휴대폰 소액결제 급증",
    "new_merchant_high_value": "처음 가는 곳 큰 금액 결제",
    "multi_line_telecom": "휴대폰 요금 여러 회선",
}
SIGNAL_KO_NEUTRAL: dict[str, str] = {"new_merchant_high_value": "큰 금액 결제"}   # 처음인지 알 수 없을 때
# AI가 본 것(_item의 ai.top_feature): 평균과 가장 다른 특징 1가지(detect.anomaly.explain_features)의 쉬운 말.
# 이미 끝난 거래를 설명하므로 지난 일로 쓴다. 숫자는 사실(건수)만 넣고 배수 같은 계산 값은 쓰지 않는다
AI_FEATURE_TEXT: dict[str, str] = {
    "log_amount": "평소에 쓰던 돈보다 큰 금액이었어요.",
    "amount_vs_p95": "평소에 쓰던 돈보다 큰 금액이었어요.",
    "hour_sin": "평소에 잘 쓰지 않던 시간이었어요.",
    "hour_cos": "평소에 잘 쓰지 않던 시간이었어요.",
    "is_night": "평소에 잘 쓰지 않던 시간이었어요.",
    "new_counterparty": "처음 거래한 상대였어요.",
    "cp_count_7d": "7일 동안 같은 상대와 거래한 횟수가 평소보다 많았어요.",
    "cp_sum_7d_ratio": "7일 동안 같은 상대에게 간 돈이 평소보다 많았어요.",
    "channel_count_7d_ratio": "7일 동안 같은 방법으로 돈을 쓴 횟수가 평소보다 많았어요.",
    "new_line": "처음 보는 휴대폰 번호였어요.",
    "is_out": "평소와 다르게 돈이 나간 거래였어요.",
}
# 밤에 쓴 거래(is_night): 큰 글씨에서 밤 / 시간이었어요처럼 한 글자가 줄 끝에 남지 않게 늦은 밤으로 쓴다(뜻은 같음)
AI_NIGHT_TEXT = "평소에 잘 쓰지 않던 늦은 밤이었어요."
