"""거래 데이터 연결 어댑터.

서비스 계층은 '어디서 온 거래인지'를 모르고 TransactionSource.load()만 부른다. 지금 연결된 것은 두 가지다.
- CsvUploadSource: 은행·카드 앱에서 내려받은 거래내역 파일(CSV). 기기 안에서만 읽는다.
- SyntheticSampleSource: 연습용 가상 거래(합성 데이터, 진짜 사람의 거래가 아님).

본 사업(실시간 분석) 단계의 연결 지점: MyDataSource
- 마이데이터 표준 API로 본인 거래를 받아 온다. 받은 뒤의 분석·판단은 지금처럼 기기 안에서만 한다.
- 필요한 것: 본인신용정보관리업(마이데이터) 허가 또는 허가 사업자 제휴, 금융사 API 이용 계약,
  사용자 인증·전송요구 동의 화면, 안드로이드 INTERNET 권한 + network_security_config로 허용 주소만 연결
  (docs/mobile.md '인터넷 연결이 필요해지는 경우').
- 이번 시제품(Pre-R&D·PoC)에는 연결할 API·허가가 없어 구현하지 않았다(load()는 NotImplementedError).
"""
from __future__ import annotations

from typing import Any, Optional, Protocol

from safepause.models import Transaction


class TransactionSource(Protocol):
    """거래를 가져오는 곳. load()는 (시간순 거래 목록, 읽기 보고서 dict)를 돌려준다."""

    kind: str

    def load(self) -> tuple[list[Transaction], dict[str, Any]]: ...


class CsvUploadSource:
    """올린 CSV 파일(바이트). 인코딩·구분자·열 이름은 data.loader가 알아본다(mapping으로 직접 지정 가능)."""

    kind = "csv_upload"

    def __init__(self, raw: bytes, mapping: Optional[dict[str, Any]] = None) -> None:
        self.raw = raw
        self.mapping = mapping

    def load(self) -> tuple[list[Transaction], dict[str, Any]]:
        from safepause.data.loader import load_csv   # numpy를 늦게 싣는다
        txns, report = load_csv(self.raw, self.mapping)
        return txns, dict(report or {})


class SyntheticSampleSource:
    """연습용 가상 거래(인물·번호가 같으면 늘 같은 거래)."""

    kind = "synthetic_sample"

    def __init__(self, persona: str, seed: int, *, scenarios: bool = True, days: int = 120) -> None:
        self.persona = persona
        self.seed = seed
        self.scenarios = scenarios
        self.days = days

    @property
    def persona_name(self) -> str:
        from safepause.data import synth
        return synth.PERSONAS[self.persona].name

    def load(self) -> tuple[list[Transaction], dict[str, Any]]:
        from safepause.data import synth
        txns = synth.make_dataset(self.persona, self.seed, days=self.days,
                                  scenarios=synth.ALL_SCENARIOS if self.scenarios else None)
        return txns, {"loaded": len(txns), "skipped": 0, "warnings": []}


class MyDataSource:
    """(본 사업 단계) 마이데이터 표준 API 연결 지점. 이번 시제품에는 구현하지 않았다(위 모듈 설명 참고)."""

    kind = "mydata"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args, self.kwargs = args, kwargs

    def load(self) -> tuple[list[Transaction], dict[str, Any]]:
        raise NotImplementedError(
            "마이데이터 연결은 본 사업 단계 과제예요(허가·API 계약·인터넷 권한 필요). 지금은 CSV 파일을 써 주세요.")


__all__ = ["CsvUploadSource", "MyDataSource", "SyntheticSampleSource", "TransactionSource"]
