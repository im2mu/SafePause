"""거래내역 CSV 가져오기 테스트(SPEC §4)."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest

from safepause.data import synth
from safepause.data.loader import LoaderError, load_csv
from safepause.models import Channel, Direction

SAMPLE = Path(__file__).resolve().parents[1] / "sample_data"


def _write(tmp_path: Path, text: str, encoding: str = "utf-8", name: str = "in.csv") -> Path:
    path = tmp_path / name
    path.write_bytes(text.encode(encoding))
    return path


# ---------------------------------------------------------------------------
# 표준 CSV
# ---------------------------------------------------------------------------

def test_standard_csv_is_read_as_is(tmp_path) -> None:
    txns = synth.make_dataset("worker", seed=1, scenarios=synth.ALL_SCENARIOS)
    path = synth.to_csv(txns, tmp_path / "std.csv")
    back, report = load_csv(path)
    assert report["format"] == "standard"
    assert report["rows"] == report["loaded"] == len(txns)
    assert report["skipped"] == 0
    assert [t.to_dict() for t in back] == [t.to_dict() for t in txns]


def test_standard_csv_bad_rows_are_skipped_and_duplicates_renamed() -> None:
    text = (",".join(synth.STANDARD_COLUMNS) + "\n"
            "a,2026-01-01T10:00:00,1000,out,card,가게,M1,,,normal\n"
            "a,2026-01-02T10:00:00,2000,out,card,가게,M1,,,normal\n"
            "b,2026-01-03T10:00:00,3000,sideways,card,가게,M1,,,normal\n")
    txns, report = load_csv(text)
    assert report["rows"] == 3 and report["loaded"] == 2 and report["skipped"] == 1
    assert report["skipped_rows"] == [4]
    assert len({t.id for t in txns}) == 2
    assert any("새 id" in w for w in report["warnings"])


def test_standard_csv_is_sorted_by_time() -> None:
    text = (",".join(synth.STANDARD_COLUMNS) + "\n"
            "b,2026-01-02T10:00:00,2000,out,card,,,,,\n"
            "a,2026-01-01T10:00:00,1000,out,card,,,,,\n")
    txns, report = load_csv(text)
    assert [t.id for t in txns] == ["a", "b"]
    assert txns[0].label is None
    assert any("정렬" in w for w in report["warnings"])


# ---------------------------------------------------------------------------
# 예시 파일(은행 내보내기 모양, 가상 거래)
# ---------------------------------------------------------------------------

def test_bank_export_example_loads_with_channels() -> None:
    txns, report = load_csv(SAMPLE / "bank_export_example.csv")
    assert report["format"] == "mapped"
    assert report["skipped"] == 0 and report["loaded"] == report["rows"] > 30
    assert report["mapping"]["datetime"] == "거래일시"
    assert report["mapping"]["out_amount"] == "출금액"
    assert report["mapping"]["in_amount"] == "입금액"
    assert report["mapping"]["counterparty"][0] == "내용"
    assert report["mapping"]["memo"] == "적요"
    counts = Counter(t.channel for t in txns)
    for ch in (Channel.CARD, Channel.TRANSFER, Channel.INCOME, Channel.ATM,
               Channel.TELECOM_BILL, Channel.MICROPAY):
        assert counts[ch] > 0, ch
    assert [t.ts for t in txns] == sorted(t.ts for t in txns)
    assert all(t.id.startswith("imp-") for t in txns)
    assert all(t.label is None for t in txns)
    assert any("추정" in w for w in report["warnings"])
    # 통신요금 회선은 내용의 번호에서 찾는다(가운데 가림)
    bill = next(t for t in txns if t.channel == Channel.TELECOM_BILL)
    assert bill.line_id == "010-****-1234"
    # 새벽 이체 예시가 들어 있다
    night = [t for t in txns if t.channel == Channel.TRANSFER and t.ts.hour < 5]
    assert len(night) == 3 and {t.counterparty for t in night} == {"김*호"}


@pytest.mark.parametrize("name", ["worker_scenarios.csv", "benefit_scenarios.csv", "student_normal.csv"])
def test_sample_synthetic_files_are_standard(name: str) -> None:
    txns, report = load_csv(SAMPLE / name)
    assert report["format"] == "standard" and report["skipped"] == 0
    assert [t.to_dict() for t in txns] == [t.to_dict() for t in synth.from_csv(SAMPLE / name)]


def test_sample_files_match_recorded_seeds() -> None:
    """sample_data/README.md에 적은 seed로 다시 만들면 같은 내용이다."""
    expected = {
        "worker_scenarios.csv": synth.make_dataset("worker", seed=1, scenarios=synth.ALL_SCENARIOS),
        "benefit_scenarios.csv": synth.make_dataset("benefit", seed=2, scenarios=synth.ALL_SCENARIOS),
        "student_normal.csv": synth.make_dataset("student", seed=3),
    }
    for name, txns in expected.items():
        assert [t.to_dict() for t in synth.from_csv(SAMPLE / name)] == [t.to_dict() for t in txns], name


# ---------------------------------------------------------------------------
# 헤더 자동 매핑
# ---------------------------------------------------------------------------

def test_cp949_file_with_amount_suffixes(tmp_path) -> None:
    text = ("거래일시,적요,출금액(원),입금액(원),내용\n"
            "2026-09-01 13:45:12,체크카드,\"12,300원\",0,동네편의점\n"
            "2026-09-02 09:00:00,급여,0,\"1,900,000원\",가상회사\n")
    txns, report = load_csv(_write(tmp_path, text, "cp949"))
    assert report["encoding"] == "cp949"
    assert [t.amount for t in txns] == [12_300, 1_900_000]
    assert txns[0].direction == Direction.OUT and txns[0].channel == Channel.CARD
    assert txns[1].direction == Direction.IN and txns[1].channel == Channel.INCOME


def test_utf8_sig_file(tmp_path) -> None:
    text = "거래일시,출금액,입금액,받는분\n2026-09-01 10:00,5000,0,엄마\n"
    txns, report = load_csv(_write(tmp_path, text, "utf-8-sig"))
    assert report["encoding"] == "utf-8-sig"
    assert txns[0].counterparty == "엄마" and txns[0].channel == Channel.TRANSFER


def test_bytes_input() -> None:
    text = "거래일시,출금액,입금액,받는분\n2026-09-01 10:00,5000,0,엄마\n"
    txns, report = load_csv(text.encode("cp949"))
    assert report["encoding"] == "cp949" and len(txns) == 1


def test_separate_date_and_time_columns() -> None:
    text = ("거래일자,거래시간,출금액,입금액,받는분\n"
            "2026.09.01,02:15:00,300000,0,김*호\n"
            "20260902,134500,10000,0,엄마\n"
            "2026-09-03,,10000,0,엄마\n")
    txns, report = load_csv(text)
    assert [t.ts for t in txns] == [datetime(2026, 9, 1, 2, 15), datetime(2026, 9, 2, 13, 45),
                                    datetime(2026, 9, 3, 12, 0)]
    assert any("낮 12시" in w for w in report["warnings"])


def test_amount_with_kind_column() -> None:
    text = ("날짜,구분,금액,거래처\n"
            "2026-09-01 10:00,출금,\"50,000\",엄마\n"
            "2026-09-02 10:00,입금,\"900,000\",복지급여\n"
            "2026-09-03 10:00,??,1000,어딘가\n")
    txns, report = load_csv(text)
    assert [(t.direction, t.amount) for t in txns] == [(Direction.OUT, 50_000), (Direction.IN, 900_000)]
    assert report["skipped"] == 1 and "구분" in " ".join(report["warnings"])
    assert txns[1].channel == Channel.INCOME


def test_amount_without_kind_uses_sign_or_needs_mapping() -> None:
    signed = "일시,금액,내용\n2026-09-01 10:00,-5000,분식집\n2026-09-02 10:00,20000,엄마\n"
    txns, report = load_csv(signed)
    assert [t.direction for t in txns] == [Direction.OUT, Direction.IN]
    assert any("부호" in w for w in report["warnings"])

    unsigned = "일시,금액,가맹점명\n2026-09-01 10:00,5000,분식집\n"
    with pytest.raises(LoaderError, match="default_direction"):
        load_csv(unsigned)
    txns, _ = load_csv(unsigned, mapping={"datetime": "일시", "amount": "금액", "merchant": "가맹점명",
                                          "counterparty": "가맹점명", "default_direction": "out"})
    assert txns[0].direction == Direction.OUT and txns[0].channel == Channel.CARD


@pytest.mark.parametrize("memo,content,expected", [
    ("휴대폰결제", "게임아이템", Channel.MICROPAY),
    ("소액결제", "콘텐츠", Channel.MICROPAY),
    ("자동이체", "가나통신", Channel.TELECOM_BILL),
    ("자동이체", "SKT 010-1234-5678", Channel.TELECOM_BILL),
    ("자동이체", "KT", Channel.TELECOM_BILL),
    ("자동이체", "LG U+", Channel.TELECOM_BILL),
    ("자동이체", "인터넷 요금", Channel.TELECOM_BILL),
    ("자동이체", "전기요금", Channel.TRANSFER),
    ("출금", "KTX 승차권", Channel.TRANSFER),
    ("ATM출금", "", Channel.ATM),
    ("현금인출", "", Channel.ATM),
    ("체크카드", "동네편의점", Channel.CARD),
    ("모바일이체", "엄마", Channel.TRANSFER),
])
def test_channel_inference(memo: str, content: str, expected: Channel) -> None:
    text = f"거래일시,적요,출금액,입금액,내용\n2026-09-01 10:00,{memo},1000,0,{content}\n"
    txns, _ = load_csv(text)
    assert txns[0].channel == expected


def test_income_channel_for_all_deposits() -> None:
    text = "거래일시,적요,출금액,입금액,내용\n2026-09-01 10:00,수당,0,50000,센터\n2026-09-02 10:00,입금,0,1000,친구\n"
    txns, _ = load_csv(text)
    assert all(t.channel == Channel.INCOME and t.direction == Direction.IN for t in txns)


def test_merchant_column_means_card() -> None:
    text = "거래일시,가맹점명,출금액,입금액\n2026-09-01 10:00,분식집,8000,0\n2026-09-02 10:00,,5000,0\n"
    txns, report = load_csv(text)
    assert txns[0].channel == Channel.CARD and txns[0].counterparty == "분식집"
    assert txns[1].channel == Channel.TRANSFER
    assert report["mapping"]["merchant"] == "가맹점명"


def test_counterparty_id_from_account_column_or_name() -> None:
    text = ("거래일시,출금액,입금액,받는분,상대계좌번호\n"
            "2026-09-01 10:00,5000,0,엄마,900-0101-100001\n"
            "2026-09-02 10:00,5000,0,엄마,\n")
    txns, _ = load_csv(text)
    assert txns[0].counterparty_id == "900-0101-100001"
    assert txns[1].counterparty_id == "엄마"  # 계좌가 비면 이름으로

    no_acct = "거래일시,출금액,입금액,받는분\n2026-09-01 10:00,5000,0, 김*호 \n2026-09-02 10:00,5000,0,김*호\n"
    txns, report = load_csv(no_acct)
    assert txns[0].counterparty_id == txns[1].counterparty_id == "김*호"
    assert any("이름이 같으면" in w for w in report["warnings"])


def test_telecom_line_from_carrier_name_when_missing() -> None:
    text = ("거래일시,적요,출금액,입금액,내용\n"
            "2026-09-01 10:00,자동이체,55000,0,가나통신\n"
            "2026-09-05 10:00,자동이체,33000,0,다라모바일 통신요금\n"
            "2026-09-06 10:00,자동이체,33000,0,마바통신 010 5555 1234\n")
    txns, report = load_csv(text)
    assert all(t.channel == Channel.TELECOM_BILL for t in txns)
    lines = [t.line_id for t in txns]
    assert lines[0] != lines[1] and all(lines)
    assert lines[2] == "010-****-1234"          # 번호는 가운데를 가림
    assert any("회선" in w for w in report["warnings"])


def test_title_rows_before_header_are_skipped() -> None:
    text = ("거래내역 조회 (가상)\n"
            "조회기간,2026-09-01 ~ 2026-09-30\n"
            "\n"
            "거래일시,출금액,입금액,내용\n"
            "2026-09-01 10:00,1000,0,분식집\n")
    txns, report = load_csv(text)
    assert len(txns) == 1
    assert report["header_row"] == 4
    assert any("머리글" in w for w in report["warnings"])


def test_bad_rows_are_skipped_with_line_numbers() -> None:
    text = ("거래일시,출금액,입금액,내용\n"
            "2026-09-01 10:00,1000,0,분식집\n"
            "합계,1000,0,\n"
            "2026-09-02 10:00,abc,,분식집\n"
            "2026-09-03 10:00,1000,2000,이상한 행\n"
            ",,,\n")
    txns, report = load_csv(text)
    assert len(txns) == 1
    assert report["rows"] == 4 and report["skipped"] == 3   # 빈 줄은 세지 않음
    assert report["skipped_rows"] == [3, 4, 5]


def test_tab_separated_text() -> None:
    text = "거래일시\t출금액\t입금액\t내용\n2026-09-01 10:00\t1,000\t0\t분식집\n"
    txns, _ = load_csv(text)
    assert txns[0].amount == 1_000


def test_korean_datetime_formats() -> None:
    text = ("일시,출금액,입금액,내용\n"
            "2026년 9월 1일 오후 2:05,1000,0,a\n"
            "2026/09/02 00:30:15,1000,0,b\n"
            "20260903 2359,1000,0,c\n")
    txns, _ = load_csv(text)
    assert [t.ts for t in txns] == [datetime(2026, 9, 1, 14, 5), datetime(2026, 9, 2, 0, 30, 15),
                                    datetime(2026, 9, 3, 23, 59)]


# ---------------------------------------------------------------------------
# mapping 지정·오류
# ---------------------------------------------------------------------------

def test_unknown_header_asks_for_mapping() -> None:
    with pytest.raises(LoaderError, match="mapping"):
        load_csv("when,howmuch,who\n2026-09-01 10:00,1000,a\n")


def test_explicit_mapping_for_unusual_headers() -> None:
    text = ("when,out,in,who,note\n"
            "2026-09-01 01:10:00,\"200,000\",,Kim,휴대폰결제\n"
            "2026-09-02 12:00:00,,5000,Lee,\n")
    mapping = {"datetime": "when", "out_amount": "out", "in_amount": "in",
               "counterparty": ["who"], "memo": "note"}
    txns, report = load_csv(text, mapping=mapping)
    assert report["format"] == "mapped"
    assert report["mapping"]["counterparty"] == ["who"]
    assert txns[0].amount == 200_000 and txns[0].channel == Channel.MICROPAY
    assert txns[1].direction == Direction.IN


def test_mapping_errors_are_korean() -> None:
    text = "when,out,in\n2026-09-01 10:00,1,0\n"
    with pytest.raises(LoaderError, match="찾지 못했어요"):
        load_csv(text, mapping={"datetime": "시각", "out_amount": "out", "in_amount": "in"})
    with pytest.raises(LoaderError, match="알 수 없는 항목"):
        load_csv(text, mapping={"datetime": "when", "amount": "out", "colour": "x"})
    with pytest.raises(LoaderError, match="꼭 있어야"):
        load_csv(text, mapping={"datetime": "when"})
    with pytest.raises(LoaderError, match="default_direction"):
        load_csv(text, mapping={"datetime": "when", "amount": "out", "default_direction": "up"})


def test_missing_file_and_empty_input(tmp_path) -> None:
    with pytest.raises(LoaderError, match="찾을 수 없어요"):
        load_csv(tmp_path / "nope.csv")
    with pytest.raises(LoaderError):
        load_csv(_write(tmp_path, "", name="empty.csv"))


def test_loader_error_is_value_error() -> None:
    assert issubclass(LoaderError, ValueError)


@pytest.mark.parametrize("mapping, key", [
    ({"datetime": "거래일시", "amount": "금액", "kind": 3}, "kind"),
    ({"datetime": "거래일시", "amount": "금액", "kind": "구분", "memo": True}, "memo"),
    ({"datetime": ["거래일시"], "amount": "금액", "kind": "구분"}, "datetime"),
    ({"datetime": "거래일시", "amount": "금액", "kind": "구분", "counterparty": ["내용", 1]}, "counterparty"),
])
def test_mapping_values_must_be_column_names(mapping, key) -> None:
    text = "거래일시,금액,구분,내용\n2026-09-01 10:00,1000,출금,가게\n"
    with pytest.raises(LoaderError, match=f"'{key}' 값은 열 이름"):
        load_csv(text, mapping)


def test_counterparty_list_mapping_still_allowed() -> None:
    text = "거래일시,금액,구분,내용\n2026-09-01 10:00,1000,출금,가게\n"
    txns, report = load_csv(text, {"datetime": "거래일시", "amount": "금액", "kind": "구분",
                                   "counterparty": ["내용"]})
    assert len(txns) == 1 and report["mapping"]["counterparty"] == ["내용"]


def test_huge_cell_is_korean_loader_error() -> None:
    text = "거래일시,출금액,입금액,내용\n2026-09-01 10:00,1000,,\"" + "가" * 140_000 + "\"\n"
    with pytest.raises(LoaderError, match="CSV 모양"):
        load_csv(text)


@pytest.mark.parametrize("amount", ["1e400", "nan", "inf", "-1e400", "1e16"])
def test_unreadable_amounts_are_skipped(amount: str) -> None:
    text = ("거래일시,출금액,입금액,내용\n"
            f"2026-09-01 10:00,{amount},,가게\n"
            "2026-09-01 11:00,1000,,가게\n")
    txns, report = load_csv(text)
    assert len(txns) == 1 and report["skipped"] == 1


@pytest.mark.parametrize("amount", ["1e400", "nan", "inf"])
def test_standard_csv_unreadable_amount_skipped(amount: str) -> None:
    header = ",".join(synth.STANDARD_COLUMNS)
    good = "a1,2026-09-01T10:00:00,1000,out,transfer,엄마,,,,"
    bad = f"a2,2026-09-01T11:00:00,{amount},out,transfer,엄마,,,,"
    txns, report = load_csv(f"{header}\n{good}\n{bad}\n")
    assert [t.id for t in txns] == ["a1"] and report["skipped"] == 1


# ---- 리뷰 수정 확인(round 2) ------------------------------------------------

def test_standard_csv_time_zones_become_naive_local() -> None:
    """시간대가 있는 행과 없는 행이 섞여도 정렬할 수 있게 모두 naive 로컬 시각으로 맞춘다."""
    text = ("id,ts,amount,direction,channel\n"
            "a,2026-09-01T10:00:00+09:00,1000,out,card\n"
            "b,2026-09-02T10:00:00,2000,out,card\n"
            "c,2026-09-03T01:00:00Z,3000,out,card\n")
    txns, report = load_csv(text)
    assert report["loaded"] == 3 and report["skipped"] == 0
    assert all(t.ts.tzinfo is None for t in txns)
    expected_a = datetime.fromisoformat("2026-09-01T10:00:00+09:00").astimezone().replace(tzinfo=None)
    assert {t.id: t.ts for t in txns}["a"] == expected_a
    assert {t.id: t.ts for t in txns}["b"] == datetime(2026, 9, 2, 10)


@pytest.mark.parametrize("text", [
    "id,ts,amount,direction,channel\na,0001-01-01T00:00:00,1000,out,card\nb,2026-09-02T10:00:00,2000,out,card\n",
    "id,ts,amount,direction,channel\na,9999-12-31T23:59:00,1000,out,card\nb,2026-09-02T10:00:00,2000,out,card\n",
    "거래일시,출금액,입금액,적요\n0001-01-01 00:00,1000,,a\n2026-09-02 10:00,2000,,b\n",
    "거래일시,출금액,입금액,적요\n9999-12-31 23:59,1000,,a\n2026-09-02 10:00,2000,,b\n",
    "거래일자,출금액,입금액,적요\n18991231,1000,,a\n20260902,2000,,b\n",
])
def test_out_of_range_years_are_skipped_with_warning(text: str) -> None:
    txns, report = load_csv(text)
    assert [t.ts.year for t in txns] == [2026]
    assert report["skipped"] == 1 and report["skipped_rows"] == [2]
    assert any("1900~2100년 밖" in w for w in report["warnings"])


# ---- 리뷰 수정 확인(round 3) ------------------------------------------------

def one_month_bank_csv() -> str:
    """정상적인 1개월치 은행형 CSV(리뷰 재현): 첫 주 치과·안경점 큰 결제, 통신사 3곳 요금(회선 열 없음)."""
    from datetime import timedelta
    start = datetime(2026, 8, 1, 10, 0)
    rows = ["거래일시,적요,출금액,입금액,내용", f'{start:%Y.%m.%d %H:%M:%S},급여,0,"1,900,000",가상회사']
    for d in range(30):
        rows.append(f'{start + timedelta(days=d, hours=2):%Y.%m.%d %H:%M:%S},체크카드,"{8000 + d * 100:,}",0,동네마트')
    rows += [
        f'{start + timedelta(days=2, hours=5):%Y.%m.%d %H:%M:%S},체크카드,"150,000",0,연세치과',
        f'{start + timedelta(days=4, hours=5):%Y.%m.%d %H:%M:%S},체크카드,"120,000",0,밝은안경',
        f'{start + timedelta(days=9, hours=1):%Y.%m.%d %H:%M:%S},자동이체,"55,000",0,SKT 휴대폰요금',
        f'{start + timedelta(days=14, hours=1):%Y.%m.%d %H:%M:%S},자동이체,"33,000",0,KT 인터넷요금',
        f'{start + timedelta(days=20, hours=1):%Y.%m.%d %H:%M:%S},자동이체,"16,500",0,LG U+ 태블릿요금',
    ]
    return "\n".join(rows) + "\n"


def test_one_month_normal_file_has_no_high() -> None:
    """[변경 r3] 파일 첫 30일은 새 가게·새 회선인지 알 수 없어 고위험(조력자 알림)이 되지 않는다."""
    from safepause.detect.engine import RiskEngine
    from safepause.models import RiskLevel

    txns, _ = load_csv(one_month_bank_csv())
    n_train = max(30, -(-len(txns) * 3 // 4))           # 서버·평가와 같은 앞 75%(올림, 최소 30건)
    engine = RiskEngine(seed=0).fit(txns[:n_train])
    for mode in ("fused", "rules"):
        results = engine.assess_many(txns, mode=mode)
        assert [a.level for a in results].count(RiskLevel.HIGH) == 0, mode
        flagged = [h for a in results for h in a.rule_hits]
        assert flagged and all(h.evidence["newness_unknown"] for h in flagged)


def test_telecom_line_without_line_column_uses_carrier_name() -> None:
    """[변경 r3] 회선 열이 없으면 적요 글자 전체가 아니라 통신사 이름으로 회선을 가른다('SKT 2월 요금'→SKT)."""
    from datetime import timedelta

    from safepause.detect.engine import RiskEngine

    start = datetime(2026, 1, 1, 10, 0)
    rows = ["거래일시,적요,출금액,입금액,내용"]
    rows += [f'{start + timedelta(days=d, hours=3):%Y.%m.%d %H:%M:%S},체크카드,"9,000",0,동네마트'
             for d in range(0, 180, 2)]
    rows += [f'2026.{m:02d}.25 09:00:00,자동이체,"55,000",0,SKT {m}월 요금' for m in range(1, 7)]
    rows += ['2026.03.10 09:00:00,자동이체,"20,000",0,헬로모바일 3월 요금',
             '2026.04.10 09:00:00,자동이체,"20,000",0,헬로모바일 4월 요금']
    txns, report = load_csv("\n".join(rows) + "\n")
    lines = {t.line_id for t in txns if t.channel == Channel.TELECOM_BILL}
    assert lines == {"통신사:SKT", "통신사:헬로모바일 요금"}
    assert any("통신사 이름으로 회선을 구분" in w for w in report["warnings"])
    results = RiskEngine(seed=0).assess_many(txns, mode="rules")
    flagged = [t.line_id for t, a in zip(txns, results)
               if any(h.code.value == "multi_line_telecom" for h in a.rule_hits)]
    # 매달 내는 SKT 요금은 적요의 달 표기가 바뀌어도 새 회선이 아니다(3월에 새로 생긴 알뜰폰만 확인)
    assert flagged == ["통신사:헬로모바일 요금"]


def test_newest_first_date_only_file_keeps_same_day_order() -> None:
    """[변경 r3] 최신순 파일은 같은 날(같은 시각) 거래도 아래 줄이 먼저다. 뒤 거래를 앞 거래의 과거로 쓰지 않는다."""
    from safepause.detect.engine import RiskEngine

    rows = ["거래일자,적요,출금액,입금액,내용",
            '2026.08.20,모바일이체(3번째),"500,000",0,박모씨',
            '2026.08.20,모바일이체(2번째),"20,000",0,박모씨',
            '2026.08.20,모바일이체(1번째),"10,000",0,박모씨']
    rows += [f'2026.08.{d:02d},체크카드,"9,000",0,동네마트' for d in range(19, 0, -1)]
    txns, report = load_csv("\n".join(rows) + "\n")
    payee = [t for t in txns if t.counterparty == "박모씨"]
    assert [t.memo for t in payee] == ["모바일이체(1번째)", "모바일이체(2번째)", "모바일이체(3번째)"]
    assert [t.id for t in payee] == ["imp-00020", "imp-00021", "imp-00022"]
    assert any("최근 거래가 위에 있는 파일" in w for w in report["warnings"])
    results = dict(zip((t.id for t in txns), RiskEngine(seed=0).assess_many(txns, mode="rules")))
    last = results["imp-00022"]
    assert [(h.code.value, h.evidence["count_7d"]) for h in last.rule_hits] == [("payee_surge", 3)]
    assert not results["imp-00020"].rule_hits              # 첫 1만 원: 뒤 거래를 쓰지 않음


def test_oldest_first_file_is_not_reversed() -> None:
    rows = ["거래일자,적요,출금액,입금액,내용", '2026.08.01,이체,"1,000",0,가', '2026.08.01,이체,"2,000",0,나',
            '2026.08.02,이체,"3,000",0,다']
    txns, report = load_csv("\n".join(rows) + "\n")
    assert [t.counterparty for t in txns] == ["가", "나", "다"]
    assert not any("최근 거래가 위에" in w for w in report["warnings"])
