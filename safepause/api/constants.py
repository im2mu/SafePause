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
MAX_EVAL_SEEDS = 20
LIVE_ID_PREFIX = "live-"                    # 보내기 전 확인(check/decide)으로 더한 거래 id
LIVE_ID_DIGITS = 9                          # live-000000001 ~ live-999999999
MAX_REMEMBERED_LIVE_IDS = 1000              # check가 준 확인 거래 id를 이만큼 기억한다(오래된 것부터 잊음)
# 보내기 전 확인으로 더한 거래의 메모(내 거래 시트에 보임). v0.3: 연습이라는 말을 쓰지 않는다(이름은 호환용으로 그대로)
PRACTICE_MEMO = "보내기 전 확인"
LEGACY_PRACTICE_MEMOS = ("안전 정지 연습",)    # v0.2가 적은 메모. 저장은 그대로 두고 화면에 줄 때만 PRACTICE_MEMO로 보인다
MIN_MONTHLY_DAYS = 14                       # 이보다 짧은 기간은 '한 달 평균'으로 늘려 말하지 않는다

# v0.2 연습 화면 안내. 평가·옛 호환을 위해 상수만 남기고, v0.3 응답(check/decide의 practice_note)에는 넣지 않는다(빈 글)
PRACTICE_NOTE = "연습 화면이에요. 실제로 돈이 나가지 않아요."
TS_NOTE = ("확인한 거래는 저장된 거래의 마지막 날에 이어서 적어요. "
           "그래서 날짜가 오늘과 달라요. 시각만 고른 대로예요.")
LIVE_IDS_USED_UP = "보내기 전 확인 번호를 다 썼어요. 동의 화면에서 모두 지운 뒤 다시 해 주세요."
TOO_BIG = "파일이 너무 커요(5MB까지)."
NO_MONITORING = ("거래 살펴보기에 동의하지 않아서 분석하지 않았어요. "
                 "동의 화면에서 거래 살펴보기를 켜 주세요.")
SUPERSEDED = ("지우기(또는 동의 끄기)가 먼저 처리돼서 이번 거래는 저장하지 않았어요. "
              "필요하면 다시 해 주세요.")
NO_FILE = "올린 파일을 찾지 못했어요. CSV 파일을 골라 다시 올려 주세요."
SYNTHETIC_NOTE = "합성 데이터 기준, 실제 피해 데이터 검증 아님"
LABELED_NOTE = ("지금 저장된 거래에는 연습용으로 섞은 걱정되는 거래가 있어요. "
                "이 숫자는 잘못 알린 비율이 아니에요.")

# ---- v0.3: 상담하는 곳·담은 거래·보낸 알림 ----
MAX_COUNSELORS = 20
COUNSELOR_KINDS: tuple[str, ...] = ("disability_center", "rights_agency", "police", "finance", "other")
# 추천 상담하는 곳(확인된 번호만). 출처
# - 장애인권익옹호기관 1644-8295: 중앙장애인권익옹호기관 naapd.or.kr/abuse/report(전국 공통, 전화·문자·카카오톡)
# - 금융감독원 1332: 금융감독원 fss.or.kr 서민금융1332
# - 경찰 112: 국번 없이
# - 지역발달장애인지원센터: 지역마다 번호가 달라 비워 둔다(사용자가 적음)
COUNSELOR_PRESETS: tuple[dict[str, str], ...] = (
    {"kind": "rights_agency", "name": "장애인권익옹호기관 (장애인학대 신고)", "phone": "1644-8295", "email": "",
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
