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
LIVE_ID_PREFIX = "live-"                    # 안전 정지 연습으로 더한 거래 id
LIVE_ID_DIGITS = 9                          # live-000000001 ~ live-999999999
MAX_REMEMBERED_LIVE_IDS = 1000              # check가 준 연습 거래 id를 이만큼 기억한다(오래된 것부터 잊음)
PRACTICE_MEMO = "안전 정지 연습"
MIN_MONTHLY_DAYS = 14                       # 이보다 짧은 기간은 '한 달 평균'으로 늘려 말하지 않는다

PRACTICE_NOTE = "연습 화면이에요. 실제로 돈이 나가지 않아요."
TS_NOTE = ("연습 거래는 저장된 거래의 마지막 날에 이어서 적어요. "
           "그래서 날짜가 오늘과 달라요. 시각만 고른 대로예요.")
TOO_BIG = "파일이 너무 커요(5MB까지)."
NO_MONITORING = ("거래 살펴보기에 동의하지 않아서 분석하지 않았어요. "
                 "'동의' 화면에서 '거래 살펴보기'를 켜 주세요.")
SUPERSEDED = ("지우기(또는 동의 끄기)가 먼저 처리돼서 이번 거래는 저장하지 않았어요. "
              "필요하면 다시 해 주세요.")
NO_FILE = "올린 파일을 찾지 못했어요. CSV 파일을 골라 다시 올려 주세요."
SYNTHETIC_NOTE = "합성 데이터 기준, 실제 피해 데이터 검증 아님"
LABELED_NOTE = ("지금 저장된 거래에는 연습용으로 섞은 걱정되는 거래가 있어요. "
                "이 숫자는 잘못 알린 비율이 아니에요.")
