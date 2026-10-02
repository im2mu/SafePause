"""SafePause 서비스 계층(프레임워크 없음).

PC판(FastAPI 로컬 서버, safepause.server.app)과 안드로이드 앱(앱 안 파이썬 Pyodide, safepause.api.bridge)이
같은 코드로 같은 요청을 처리한다. HTTP 상태 코드로 바꾸는 일은 이 계층의 ServiceError가 맡는다.

- constants: 가벼운 상수(numpy·scikit-learn 없이 import 가능)
- schemas: 요청 형식(pydantic)과 한국어 입력 오류 문구
- service: 업무 로직(동의·조력자·상담하는 곳·거래·담은 거래·알림 기록·받는 사람 추천·돈 흐름 분석·보내기 전 확인·성능 확인·지우기·내보내기)
- router: (메서드, 경로) → service 호출. 모바일 브리지가 쓴다
- bridge: Pyodide 진입점(init/warm/handle)
"""
