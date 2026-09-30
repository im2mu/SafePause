# SafePause 컨테이너(선택 사항). 작성 환경에 Docker가 없어 빌드·실행을 확인하지 않았다(미검증).
#
# 빌드:  docker build -t safepause .
# 명령행: docker run --rm safepause python -m safepause demo
#         docker run --rm -v "$PWD/eval_out:/app/eval_out" safepause python -m safepause eval --seeds 5
# 화면:  서버는 명세상 127.0.0.1에만 바인드하므로 -p 포트 연결로는 컨테이너 밖에서 열 수 없다.
#         Linux에서는 호스트 네트워크를 쓰면 http://127.0.0.1:8765 로 열린다:
#         docker run --rm --network host -v safepause-data:/data safepause
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SAFEPAUSE_HOME=/data

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY safepause ./safepause
COPY sample_data ./sample_data

# 저장 데이터는 /data(볼륨)에만 둔다. root가 아닌 사용자로 실행한다.
RUN useradd --create-home --uid 10001 safepause \
    && mkdir -p /data /app/eval_out \
    && chown -R safepause:safepause /data /app/eval_out
USER safepause
VOLUME ["/data"]

CMD ["python", "-m", "safepause", "serve", "--no-browser"]
