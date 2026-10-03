"""거래내역 CSV 가져오기 테스트(SPEC §4)."""
from __future__ import annotations

import csv
import io
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest

from safepause.data import synth
from safepause.data.loader import LoaderError, _find_phone, _parse_amount, load_csv
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


def test_telecom_line_is_empty_without_number() -> None:
    """[변경 r6] 회선 번호(전화번호)를 모르면 회선을 비운다. 이름으로 회선을 만들지 않는다."""
    text = ("거래일시,적요,출금액,입금액,내용\n"
            "2026-09-01 10:00,자동이체,55000,0,가나통신\n"
            "2026-09-05 10:00,자동이체,33000,0,다라모바일 통신요금\n"
            "2026-09-06 10:00,자동이체,33000,0,마바통신 010 5555 1234\n")
    txns, report = load_csv(text)
    assert all(t.channel == Channel.TELECOM_BILL for t in txns)
    lines = [t.line_id for t in txns]
    assert lines[:2] == ["", ""]
    assert lines[2] == "010-****-1234"          # 번호는 가운데를 가림
    assert any("통신요금 2건은 회선(전화번호) 정보가 없어" in w for w in report["warnings"])


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


def test_telecom_line_without_line_column_is_left_empty() -> None:
    """[변경 r6, r3 대체] 회선 열·번호가 없으면 통신사 이름으로 회선을 만들지 않고 비운다.

    이름만으로는 같은 통신사의 두 회선도, 한 사람의 휴대폰·인터넷도 가를 수 없어 '휴대폰 요금이 여러 개'
    판단이 틀린다(리뷰 재현: 통행요금·택배요금·렌탈요금이 이름별 회선이 되어 고위험 2건). 적요의 달 표기가
    바뀌어도(r3) 회선이 비어 있으니 새 회선이 생기지 않는다.
    """
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
    bills = [t for t in txns if t.channel == Channel.TELECOM_BILL]
    assert len(bills) == 8 and {t.line_id for t in bills} == {""}
    assert any("통신요금 8건은 회선(전화번호) 정보가 없어 휴대폰 요금 여러 회선 판단에서 뺐어요" in w
               for w in report["warnings"])
    results = RiskEngine(seed=0).assess_many(txns, mode="rules")
    assert not any(h.code.value == "multi_line_telecom" for a in results for h in a.rule_hits)


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


# ---- 리뷰 수정 확인(r6: CSV 로더 리뷰 data_review.md) --------------------------------------
# 사례 번호는 data_review.md 문제 목록 번호. e2e 사례는 리뷰 스크립트(e2e.py·e2e2.py)를 옮긴 것.

BANK_HEADER = "거래일시,적요,출금액,입금액,내용"
NBSP, THIN_SPACE, IDEO_SPACE = chr(0xA0), chr(0x2009), chr(0x3000)
MINUS_SIGN, FULLWIDTH_WON, BACKSLASH = chr(0x2212), chr(0xFFE6), chr(92)
E2E_START = date(2026, 6, 1)
E2E_LAST = E2E_START + timedelta(days=80)


def _bank(rows: list[str], header: str = BANK_HEADER) -> str:
    return "\n".join([header, *rows]) + "\n"


def _daily_rows(telecom: str = "SKT") -> list[tuple[datetime, str, int, int, str]]:
    """90일 정상 거래(e2e.py base_rows): (일시, 적요, 출금, 입금, 내용)."""
    rows = []
    for d in range(90):
        day = datetime.combine(E2E_START + timedelta(days=d), time(0))
        rows.append((day.replace(hour=12, minute=10 + d % 40), "체크카드", 4000 + (d * 370) % 9000, 0,
                     ["동네편의점", "분식집", "카페"][d % 3]))
        if day.weekday() == 5:
            rows.append((day.replace(hour=14), "모바일이체", 50000, 0, "엄마"))
        if day.day == 10:
            rows.append((day.replace(hour=9, minute=30), "급여", 0, 1_900_000, "가상회사"))
        if day.day == 25:
            rows.append((day.replace(hour=10), "통신요금", 55000, 0, telecom))
    return rows


def _at(offset: int, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(E2E_LAST + timedelta(days=offset), time(hour, minute))


def _render(rows, dt_fmt=lambda t: t.strftime("%Y.%m.%d %H:%M:%S"), who: str = "내용",
            split=None, post: tuple[str, ...] = ()) -> str:
    """은행형 CSV 글(e2e.py render). split=(날짜 fmt 함수, 시각 fmt 함수)면 거래일자·거래시간 두 열."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    dt_cols = ["거래일자", "거래시간"] if split else ["거래일시"]
    writer.writerow(dt_cols + ["적요", "출금액", "입금액", "잔액", who, "거래점"])
    balance = 5_000_000
    for ts, memo, out, inc, name in sorted(rows, key=lambda r: r[0]):
        balance += inc - out
        dt = [split[0](ts), split[1](ts)] if split else [dt_fmt(ts)]
        writer.writerow(dt + [memo, f"{out:,}" if out else "0", f"{inc:,}" if inc else "0", f"{balance:,}",
                              name, "본점"])
    for line in post:
        buf.write(line + "\r\n")
    return buf.getvalue()


def _evaluate(text: str) -> tuple[list, dict]:
    from safepause.eval.metrics import evaluate_file

    txns, _ = load_csv(text)
    return txns, evaluate_file(txns, mode="rules", seed=0)


def _signals(result: dict) -> Counter:
    return Counter((s, a["level"]) for a in result["alert_list"] for s in a["signals"] or ["anomaly"])


# ---- 1. 영어 AM/PM, 끝까지 일치 ----------------------------------------------------------------

@pytest.mark.parametrize("cell, expected", [
    ("2026-09-01 01:05:00 PM", datetime(2026, 9, 1, 13, 5)),
    ("2026-09-01 1:05 pm", datetime(2026, 9, 1, 13, 5)),
    ("2026-09-01 12:30:00 AM", datetime(2026, 9, 1, 0, 30)),
    ("2026-09-01 12:10:00 PM", datetime(2026, 9, 1, 12, 10)),
    ("2026-09-01 11:59:59 A.M.", datetime(2026, 9, 1, 11, 59, 59)),
    ("2026-09-01 PM 2:05", datetime(2026, 9, 1, 14, 5)),
    ("2026-09-01 오후 1:05:00", datetime(2026, 9, 1, 13, 5)),
    ("2026-09-01 오전 12:05", datetime(2026, 9, 1, 0, 5)),
    ("2026.09.01(화) 13:05", datetime(2026, 9, 1, 13, 5)),
    ("2026-09-01 13:05:00.000", datetime(2026, 9, 1, 13, 5)),
    ("2026년 9월 1일 13시 5분 7초", datetime(2026, 9, 1, 13, 5, 7)),
])
def test_am_pm_and_known_tails_are_read(cell: str, expected: datetime) -> None:
    txns, _ = load_csv(_bank([f"{cell},체크카드,1000,0,가게"]))
    assert txns[0].ts == expected


def test_time_zone_suffix_becomes_local_time() -> None:
    txns, _ = load_csv(_bank(["2026-09-01T10:00:00+09:00,체크카드,1000,0,가게"]))
    assert txns[0].ts == datetime.fromisoformat("2026-09-01T10:00:00+09:00").astimezone().replace(tzinfo=None)


@pytest.mark.parametrize("cell", [
    "2026-09-01 13:05 xyz", "2026-09-01 13:05:00 1", "2026-09-01 오전 13:00", "2026-09-01 1:05 PM 오후",
    "2026-09-01 abc", "2026.09.01 25:10", "2026-09-01 13:05 KST",
])
def test_unknown_tail_after_datetime_is_rejected(cell: str) -> None:
    txns, report = load_csv(_bank([f"{cell},체크카드,1000,0,가게", "2026-09-02 10:00,체크카드,2000,0,가게"]))
    assert [t.amount for t in txns] == [2000]
    assert report["skipped_rows"] == [2]
    assert "2번째 줄(날짜를 읽지 못함)" in " ".join(report["warnings"])


def test_am_pm_time_column() -> None:
    text = ("거래일자,거래시간,적요,출금액,입금액,내용\n"
            "2026-09-01,01:05:00 PM,체크카드,1000,0,가\n"
            "2026-09-02,12:15 AM,체크카드,1000,0,가\n"
            "2026-09-03,오후 3:00,체크카드,1000,0,가\n")
    txns, _ = load_csv(text)
    assert [t.ts for t in txns] == [datetime(2026, 9, 1, 13, 5), datetime(2026, 9, 2, 0, 15),
                                    datetime(2026, 9, 3, 15, 0)]


def test_am_pm_file_gives_same_result_as_24h_file() -> None:
    """e2e2 1b: 엄마에게 낮 송금 2건. 수정 전 AM/PM 파일은 PM을 버려 심야 알림 4건(고위험 1)."""
    rows = _daily_rows() + [(_at(0, 14), "모바일이체", 50000, 0, "엄마"),
                            (_at(2, 15, 30), "모바일이체", 50000, 0, "엄마")]
    ampm = lambda t: t.strftime("%Y-%m-%d %I:%M:%S ") + ("PM" if t.hour >= 12 else "AM")  # noqa: E731
    txns_24, result_24 = _evaluate(_render(rows))
    txns_ap, result_ap = _evaluate(_render(rows, dt_fmt=ampm))
    assert [t.ts for t in txns_ap] == [t.ts for t in txns_24]
    assert result_ap["alerts"] == result_24["alerts"] == 0


# ---- 2. 상대 이름 열 --------------------------------------------------------------------------

@pytest.mark.parametrize("header", ["보낸분/받는분", "받는분/보낸분", "보낸분 / 받는분", "거래내용", "기재내용",
                                    "받는사람", "상대방", "수취인명"])
def test_counterparty_column_aliases(header: str) -> None:
    txns, report = load_csv(_bank(["2026-09-01 10:00,모바일이체,5000,0,엄마"],
                                  header=f"거래일시,적요,출금액,입금액,{header}"))
    assert txns[0].counterparty == txns[0].counterparty_id == "엄마"
    assert txns[0].memo == "모바일이체"
    assert report["mapping"]["counterparty"] == [header.replace(" ", "")]
    assert not any("받는 사람 열을 찾지 못해" in w for w in report["warnings"])


def test_memo_is_not_counterparty_and_missing_column_is_warned() -> None:
    txns, report = load_csv("거래일시,적요,출금액,입금액\n2026-09-01 10:00,모바일이체,5000,0\n"
                            "2026-09-02 10:00,모바일이체,7000,0\n")
    assert [(t.counterparty, t.counterparty_id, t.memo) for t in txns] == [("", "", "모바일이체")] * 2
    assert "counterparty" not in report["mapping"] and report["mapping"]["memo"] == "적요"
    joined = " ".join(report["warnings"])
    assert "받는 사람 열을 찾지 못해 한 사람에게 송금 집중은 판단하기 어려워요" in joined
    assert "이름이 같으면" not in joined


def test_explicit_memo_counterparty_mapping_is_still_allowed() -> None:
    txns, _ = load_csv("거래일시,적요,출금액,입금액\n2026-09-01 10:00,엄마,5000,0\n",
                       mapping={"datetime": "거래일시", "out_amount": "출금액", "in_amount": "입금액",
                                "counterparty": "적요"})
    assert txns[0].counterparty == "엄마"


def test_slash_counterparty_header_gives_same_alerts_as_content_header() -> None:
    """e2e 2: 새 상대에게 4회 송금. 수정 전 '보낸분/받는분' 파일은 적요가 상대가 되어 고위험 0건(내용 열은 3건)."""
    rows = _daily_rows() + [(_at(k, 15), "모바일이체", 150000, 0, "이*민") for k in (0, 1, 3, 4)]
    _, by_content = _evaluate(_render(rows, who="내용"))
    txns, by_slash = _evaluate(_render(rows, who="보낸분/받는분"))
    assert {t.counterparty for t in txns if t.channel == Channel.TRANSFER} == {"엄마", "이*민"}
    assert by_content["high"] == by_slash["high"] == 3
    assert _signals(by_slash) == _signals(by_content)


# ---- 3. 통신요금 분류·회선 ------------------------------------------------------------------------

@pytest.mark.parametrize("memo, content, expected", [
    ("자동이체", "하이패스 통행요금", Channel.TRANSFER),
    ("자동이체", "택배요금", Channel.TRANSFER),
    ("자동이체", "정수기 렌탈요금", Channel.TRANSFER),
    ("자동이체", "아파트 관리비", Channel.TRANSFER),
    ("체크카드", "KT&G 상상마당", Channel.CARD),
    ("체크카드", "케이티앤지", Channel.CARD),
    ("체크카드", "OO쇼핑 통신판매", Channel.CARD),
    ("체크카드", "대한정보통신", Channel.CARD),
    ("체크카드", "현금영수증 발급 가게", Channel.CARD),
    ("자동이체", "SK텔레콤", Channel.TELECOM_BILL),
    ("자동이체", "SKT통신요금", Channel.TELECOM_BILL),
    ("자동이체", "LGU+", Channel.TELECOM_BILL),
    ("자동이체", "LG유플러스", Channel.TELECOM_BILL),
    ("자동이체", "KT 인터넷", Channel.TELECOM_BILL),
    ("자동이체", "헬로모바일", Channel.TELECOM_BILL),
    ("자동이체", "U+알뜰모바일", Channel.TELECOM_BILL),
    ("자동이체", "세종텔레콤", Channel.TELECOM_BILL),
    ("자동이체", "휴대폰 요금", Channel.TELECOM_BILL),
    ("자동이체", "인터넷요금", Channel.TELECOM_BILL),
    ("통신요금", "가게", Channel.TELECOM_BILL),
    ("현금인출", "", Channel.ATM),
])
def test_telecom_classification_is_narrow(memo: str, content: str, expected: Channel) -> None:
    txns, _ = load_csv(_bank([f"2026-09-01 10:00,{memo},1000,0,{content}"]))
    assert txns[0].channel == expected


def test_non_telecom_fees_make_no_multi_line_alerts() -> None:
    """e2e 3: 통행요금·택배요금·렌탈요금 자동이체. 수정 전 통신요금으로 분류돼 '여러 회선' 고위험 2건·주의 1건."""
    rows = _daily_rows() + [(_at(0, 10), "자동이체", 3100, 0, "하이패스 통행요금"),
                            (_at(3, 10), "자동이체", 4000, 0, "택배요금"),
                            (_at(6, 10), "자동이체", 29900, 0, "정수기 렌탈요금")]
    txns, result = _evaluate(_render(rows))
    fees = {t.counterparty: t.channel for t in txns if t.counterparty.endswith("요금")}
    assert fees == {"하이패스 통행요금": Channel.TRANSFER, "택배요금": Channel.TRANSFER,
                    "정수기 렌탈요금": Channel.TRANSFER}
    assert result["alerts"] == 0


def test_multi_line_uses_phone_numbers_only() -> None:
    """이름만 있는 통신요금(SKT·KT·LG U+)은 회선을 비워 '여러 회선' 판단을 하지 않고, 번호가 있으면 한다."""
    named = _daily_rows("SKT") + [(_at(1, 10), "자동이체", 33000, 0, "KT 휴대폰요금"),
                                  (_at(4, 10), "자동이체", 44000, 0, "LG U+ 휴대폰요금")]
    txns, result = _evaluate(_render(named))
    assert {t.line_id for t in txns if t.channel == Channel.TELECOM_BILL} == {""}
    assert not any("multi_line_telecom" in a["signals"] for a in result["alert_list"])

    numbered = _daily_rows("SKT 010-1111-2222") + [(_at(1, 10), "자동이체", 33000, 0, "KT 010-2222-3333"),
                                                   (_at(4, 10), "자동이체", 44000, 0, "LG U+ +82 10-4444-5555")]
    txns, result = _evaluate(_render(numbered))
    assert {t.line_id for t in txns if t.channel == Channel.TELECOM_BILL} == {
        "010-****-2222", "010-****-3333", "010-****-5555"}
    assert _signals(result)[("multi_line_telecom", "high")] == 1


# ---- 4. 엑셀 숫자형 시각 --------------------------------------------------------------------------

def test_excel_numeric_time_column_is_zero_filled() -> None:
    text = ("거래일자,거래시간,적요,출금액,입금액,내용\n"
            "2026-09-01,130500,체크카드,1000,0,가\n"
            "2026-09-02,91030,체크카드,1000,0,가\n"
            "2026-09-03,21705,체크카드,1000,0,가\n"
            "2026-09-04,500,체크카드,1000,0,가\n"
            "2026-09-05,abc,체크카드,1000,0,가\n"
            "2026-09-06,,체크카드,1000,0,가\n")
    txns, report = load_csv(text)
    assert [t.ts.time() for t in txns] == [time(13, 5), time(9, 10, 30), time(2, 17, 5), time(0, 5),
                                           time(12, 0), time(12, 0)]
    joined = " ".join(report["warnings"])
    assert "시각을 읽지 못한 1건은 낮 12시로 두었어요" in joined
    assert "시각이 없는 거래 1건은 낮 12시로 두었어요" in joined


def test_four_digit_time_column_stays_hour_minute() -> None:
    text = ("거래일자,거래시간,출금액,입금액,내용\n"
            "20260901,905,1000,0,가\n20260902,1305,1000,0,가\n20260903,30,1000,0,가\n")
    txns, _ = load_csv(text)
    assert [t.ts.time() for t in txns] == [time(9, 5), time(13, 5), time(0, 30)]


def test_combined_datetime_with_five_digit_time() -> None:
    txns, _ = load_csv(_bank(["20260901 91030,체크카드,1000,0,가", "20260902 2359,체크카드,1000,0,가"]))
    assert [t.ts for t in txns] == [datetime(2026, 9, 1, 9, 10, 30), datetime(2026, 9, 2, 23, 59)]


def test_numeric_time_file_keeps_night_alerts() -> None:
    """e2e 4: 심야 이체 3건. 수정 전 숫자형 시각(21705)이 12:00이 되어 심야 고위험 2건이 사라졌다."""
    rows = _daily_rows() + [(_at(0, 2, 17), "모바일이체", 300000, 0, "김*호"),
                            (_at(1, 3, 5), "모바일이체", 300000, 0, "김*호"),
                            (_at(2, 1, 40), "모바일이체", 300000, 0, "김*호")]
    as_text = (lambda t: t.strftime("%Y%m%d"), lambda t: t.strftime("%H%M%S"))
    as_number = (lambda t: t.strftime("%Y%m%d"), lambda t: str(int(t.strftime("%H%M%S"))))
    txns_text, by_text = _evaluate(_render(rows, split=as_text))
    txns_num, by_number = _evaluate(_render(rows, split=as_number))
    assert [t.ts for t in txns_num] == [t.ts for t in txns_text]
    assert _signals(by_number) == _signals(by_text)
    assert _signals(by_number)[("night_repeat_transfer", "high")] == 2


# ---- 5. 구분자 -----------------------------------------------------------------------------------

@pytest.mark.parametrize("delimiter", [",", "\t", ";", "|"])
def test_delimiters_are_detected_by_header(delimiter: str) -> None:
    rows = [["거래일시", "적요", "출금액", "입금액", "잔액", "내용"],
            ["2026-09-01 10:00", "체크카드", "1,234,000", "0", "5,000,000", "가게"],
            ["2026-09-02 10:00", "급여", "0", "2,000,000", "7,000,000", "회사"]]
    body = [[f'"{c}"' if delimiter == "," and "," in c else c for c in r] for r in rows]
    txns, report = load_csv("\n".join(delimiter.join(r) for r in body) + "\n")
    assert report["delimiter"] == delimiter
    assert [(t.direction, t.amount) for t in txns] == [(Direction.OUT, 1_234_000), (Direction.IN, 2_000_000)]


def test_tab_file_with_comma_notice_lines() -> None:
    notice = ["[가상은행] 거래내역 조회", "조회기간: 2026.09.01 ~ 2026.09.30, 조회일: 2026.10.01",
              "계좌번호: 000-0000-0000, 예금주: 홍*동"]
    text = "\n".join(notice + ["거래일시\t적요\t출금액\t입금액\t내용", "2026-09-01 10:00\t체크카드\t12,000\t0\t가게"])
    txns, report = load_csv(text + "\n")
    assert report["delimiter"] == "\t" and report["header_row"] == 4 and txns[0].amount == 12_000


# ---- 6. 금액 표기 ---------------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("₩12,000", 12000), (FULLWIDTH_WON + "12,000", 12000), (BACKSLASH + "12,000", 12000),
    ("KRW 12,000", 12000), ("12,000 krw", 12000), ("12,000원", 12000),
    (NBSP + "12,000" + NBSP, 12000), ("12" + NBSP + "000", 12000), (IDEO_SPACE + "5,000", 5000),
    ("1" + THIN_SPACE + "000", 1000),
    ("5,000-", -5000), (MINUS_SIGN + "5,000", -5000), ("△5,000", -5000), ("(5,000)", -5000),
    ("-5,000", -5000), ("", 0), ("-", 0), ("abc", None), ("12,000원원x", None),
    ("1,000.5", 1001), ("2.5", 3), ("0.4", 0),
])
def test_amount_notations(text: str, expected: int | None) -> None:
    assert _parse_amount(text) == expected


def test_cp949_file_with_fullwidth_won_sign(tmp_path) -> None:
    text = _bank([f'2026-09-01 10:00,체크카드,"{FULLWIDTH_WON}12,000",0,가게',
                  f'2026-09-02 10:00,급여,0,"{FULLWIDTH_WON}1,900,000",회사'])
    txns, report = load_csv(_write(tmp_path, text, "cp949"))
    assert report["encoding"] == "cp949" and [t.amount for t in txns] == [12_000, 1_900_000]


def test_signed_amount_column_with_trailing_minus_and_triangle() -> None:
    text = "일시,금액,내용\n2026-09-01 10:00,5000-,분식집\n2026-09-02 10:00,△3000,카페\n2026-09-03 10:00,9000,엄마\n"
    txns, _ = load_csv(text)
    assert [(t.direction, t.amount) for t in txns] == [(Direction.OUT, 5000), (Direction.OUT, 3000),
                                                       (Direction.IN, 9000)]


# ---- 7. 날짜 끝까지 일치, 합계·소계 ---------------------------------------------------------------

def test_total_and_subtotal_rows_are_skipped_with_warning() -> None:
    text = _bank(["2026-09-01 10:00,체크카드,1000,0,가게",
                  "2026-09-02 10:00,소계,1000,0,",
                  '2026.09.01 ~ 2026.09.30 합계,,"1,000",0,',
                  "2026-09-03 10:00,체크카드,2000,0,가게",
                  "2026.09.01 ~ 2026.09.30,,3000,0,",
                  "총 합계,,3000,0,"])
    txns, report = load_csv(text)
    assert [t.amount for t in txns] == [1000, 2000]
    assert report["skipped_rows"] == [3, 4, 6, 7]
    joined = " ".join(report["warnings"])
    assert "합계·소계 줄 4개는 거래가 아니라서 뺐어요" in joined and "3번째 줄(합계·소계 줄)" in joined


@pytest.mark.parametrize("post", [
    ('2026.06.01 ~ 2026.08.29 출금합계,,"999,999",0,,,',),
    ('2026.08.22 소계,,"200,000",0,,,', '2026.08.24 소계,,"250,000",0,,,', '2026.08.26 소계,,"150,000",0,,,'),
])
def test_total_rows_do_not_become_transactions(post: tuple[str, ...]) -> None:
    """e2e 5·5b: 날짜로 시작하는 합계·소계 행. 수정 전에는 가짜 출금 거래(1건·3건)가 되었다."""
    plain, _ = load_csv(_render(_daily_rows()))
    with_total, report = load_csv(_render(_daily_rows(), post=post))
    assert [t.to_dict() for t in with_total] == [t.to_dict() for t in plain]
    assert report["skipped"] == len(post)


# ---- 8. 열 이름 별칭, date_format, 무엇이 없는지 ---------------------------------------------------

@pytest.mark.parametrize("header", [
    "거래일시,적요,출금(원),입금(원),잔액(원),내용",
    "거래일시,적요,지급(원),입금(원),거래후잔액(원),기재내용",
    "거래일시,적요,찾으신금액,맡기신금액,잔액,내용",
    "거래일시,적요,출금금액,입금금액,거래후잔액,거래내용",
    "거래일자,거래시간,적요,출금액,입금액,잔액,내용",
])
def test_bank_column_aliases(header: str) -> None:
    rows = ["2026-09-01 10:00,체크카드,5000,0,10000,가게", "2026-09-02 10:00,급여,0,90000,100000,회사"]
    if header.startswith("거래일자"):
        rows = [r.replace(" ", ",", 1) for r in rows]
    txns, report = load_csv(_bank(rows, header=header))
    assert [(t.direction, t.amount, t.counterparty) for t in txns] == [
        (Direction.OUT, 5000, "가게"), (Direction.IN, 90000, "회사")]
    assert txns[0].ts == datetime(2026, 9, 1, 10, 0)


@pytest.mark.parametrize("header", ["이용일시,가맹점명,이용금액", "승인일시,가맹점명,승인금액"])
def test_card_statement_amounts_are_spending(header: str) -> None:
    text = f"{header}\n2026-09-01 12:00,분식집,8000\n2026-09-02 12:00,카페,4500\n2026-09-03 12:00,카페,-4500\n"
    txns, report = load_csv(text)
    assert [(t.direction, t.amount, t.channel, t.counterparty) for t in txns] == [
        (Direction.OUT, 8000, Channel.CARD, "분식집"), (Direction.OUT, 4500, Channel.CARD, "카페")]
    assert report["skipped_rows"] == [4]
    assert any("카드 이용내역으로 보고" in w for w in report["warnings"])


def test_date_format_mapping() -> None:
    text = _bank(["09/01/2026,체크카드,1000,0,가", "09/02/2026,체크카드,2000,0,가"])
    with pytest.raises(LoaderError, match="date_format"):
        load_csv(text)
    txns, report = load_csv(text, mapping={"date_format": "%m/%d/%Y"})   # 열은 자동, 날짜 모양만 지정
    assert [t.ts for t in txns] == [datetime(2026, 9, 1, 12), datetime(2026, 9, 2, 12)]
    assert report["mapping"]["date_format"] == "%m/%d/%Y" and report["mapping"]["out_amount"] == "출금액"
    mapping = {"datetime": "when", "out_amount": "out", "in_amount": "in", "date_format": "%m/%d/%Y %I:%M %p"}
    txns, _ = load_csv("when,out,in\n9/1/2026 1:05 PM,1000,\n9/2/2026 1:05 PM tail,1000,\n", mapping=mapping)
    assert [t.ts for t in txns] == [datetime(2026, 9, 1, 13, 5)]           # 끝까지 맞아야 한다


def test_date_format_with_separate_time_column() -> None:
    text = "거래일자,거래시간,출금액,입금액,내용\n26.09.01,02:10,1000,0,가\n"
    txns, _ = load_csv(text, mapping={"date_format": "%y.%m.%d"})
    assert txns[0].ts == datetime(2026, 9, 1, 2, 10)


@pytest.mark.parametrize("fmt", [3, "", "no-percent", "%Q"])
def test_bad_date_format_is_korean_error(fmt) -> None:
    with pytest.raises(LoaderError, match="date_format은"):
        load_csv(_bank(["2026-09-01 10:00,체크카드,1000,0,가"]), mapping={"date_format": fmt})


def test_header_error_says_which_column_is_missing() -> None:
    with pytest.raises(LoaderError, match=r"머리글\(열 이름\)에서 날짜 열\(") as e:
        load_csv("시점,출금액,입금액\nx,1,0\n")
    assert "mapping" in str(e.value)
    with pytest.raises(LoaderError, match=r"머리글\(열 이름\)에서 금액 열\("):
        load_csv("거래일시,얼마\n2026-09-01,1\n")
    with pytest.raises(LoaderError, match="날짜 열과 금액 열을 찾지 못했어요"):
        load_csv("가,나\n1,2\n")


# ---- 9. 파일 종류 판별, UTF-16 ---------------------------------------------------------------------

def _zip_without_workbook() -> bytes:
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", "<document/>")
    return buf.getvalue()


@pytest.mark.parametrize("data, fragment", [
    (b"PK\x03\x04" + b"\x00" * 30, "엑셀 파일(.xlsx)을 읽지 못했어요"),     # 손상된 xlsx(zip)
    (_zip_without_workbook(), "엑셀(.xlsx)이 아닌 압축 파일"),                  # .docx 같은 다른 zip
    (bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 30, "엑셀 파일(.xls)"),
    (b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n", "PDF 파일은 읽지 못해요"),
    (b"\x89PNG\r\n\x1a\n" + b"\x00" * 30, "사진(이미지) 파일은 읽지 못해요"),
    (b"\xff\xd8\xff\xe0" + b"\x00" * 30, "사진(이미지) 파일은 읽지 못해요"),
    ("<html><body><table><tr><th>거래일시</th></tr></table></body></html>".encode("utf-8"), "웹 페이지(HTML)"),
    ("\r\n  <!DOCTYPE html><html><table></table></html>".encode("cp949"), "웹 페이지(HTML)"),
])
def test_non_csv_files_get_matching_guidance(data: bytes, fragment: str) -> None:
    with pytest.raises(LoaderError) as e:
        load_csv(data)
    # v0.3 수정 AUG-02: 엑셀(.xlsx)은 바로 읽으므로 PDF·사진은 엑셀이나 CSV로 내려받으라고 안내한다
    # (2026-10-03: 옛 엑셀(.xls)도 읽으므로 안내에 .xls를 넣었다. 손상된 .xls는 CSV로 저장하라고 안내)
    message = str(e.value)
    assert fragment in message and ("CSV UTF-8" in message or "엑셀이나 CSV" in message or ".csv, .xls, .xlsx" in message)
    assert "인코딩" not in message


def test_html_text_input_is_rejected() -> None:
    with pytest.raises(LoaderError, match="웹 페이지"):
        load_csv("<table>\n<tr><td>거래일시</td></tr>\n</table>\n")


@pytest.mark.parametrize("big_endian", [False, True])
def test_utf16_with_bom_is_read(big_endian: bool) -> None:
    text = "거래일시\t적요\t출금액\t입금액\t내용\n2026-09-01 10:00\t체크카드\t1,000\t0\t가게\n"
    data = b"\xfe\xff" + text.encode("utf-16-be") if big_endian else text.encode("utf-16")
    txns, report = load_csv(data)
    assert report["encoding"] == "utf-16" and report["delimiter"] == "\t"
    assert [(t.amount, t.counterparty) for t in txns] == [(1000, "가게")]


@pytest.mark.parametrize("text", ["\r\n\r\n\r\n", ",,,\r\n,,,\r\n", " \n"])
def test_blank_only_file_is_empty(text: str) -> None:
    with pytest.raises(LoaderError, match="파일이 비어 있어요"):
        load_csv(text.encode("utf-8"))


# ---- 10. 모두 건너뛰면 이유를 담은 오류 ---------------------------------------------------------------

ALL_SKIPPED = _bank(["09/01/2026 10:00,체크카드,1000,0,가", "09/02/2026 10:00,체크카드,1000,0,가",
                     "합계,,2000,0,", "2026-09-03 10:00,체크카드취소,1000,0,가"])


def test_all_rows_skipped_error_lists_reasons() -> None:
    with pytest.raises(LoaderError) as e:
        load_csv(ALL_SKIPPED)
    message = str(e.value)
    assert message.startswith("읽을 수 있는 거래가 없어요. 4줄을 모두 건너뛰었어요. 건너뛴 이유: "
                              "날짜를 읽지 못함 2줄, 합계·소계 줄 1줄, 취소 거래 1줄.")
    assert '"date_format"' in message


def test_all_rows_skipped_error_keeps_at_most_three_reasons() -> None:
    text = _bank(["x,체크카드,1000,0,가", "합계,,1,0,", "2026-09-03 10:00,취소,1000,0,가",
                  "2026-09-04 10:00,이체,abc,,가", "2026-09-05 10:00,이체,1000,2000,가"])
    with pytest.raises(LoaderError) as e:
        load_csv(text)
    assert str(e.value).count("줄,") == 2 and "5줄을 모두 건너뛰었어요" in str(e.value)


def test_header_only_and_all_bad_standard_files() -> None:
    with pytest.raises(LoaderError, match="머리글 아래에 거래 줄이 없어요"):
        load_csv("거래일시,출금액,입금액\n")
    header = ",".join(synth.STANDARD_COLUMNS)
    with pytest.raises(LoaderError, match="건너뛴 이유: 형식 오류 1줄, 금액이 0원 이하 1줄"):
        load_csv(f"{header}\na,2026-09-01T10:00:00,1000,sideways,card,,,,,\nb,2026-09-01T10:00:00,0,out,card,,,,,\n")


def test_upload_all_skipped_shows_reasons_through_server(tmp_path) -> None:
    """서버는 LoaderError 문구를 그대로 400 detail로 보여 준다(화면에 이유가 보인다)."""
    from fastapi.testclient import TestClient

    from safepause.server.app import create_app

    app = create_app(tmp_path / "home", now=lambda: datetime(2026, 9, 30, 12))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-SafePause": "1"}) as client:
        assert client.put("/api/consent", json={"monitoring": True}).status_code == 200
        r = client.post("/api/data/upload",
                        files={"file": ("x.csv", ALL_SKIPPED.encode("utf-8"), "text/csv")})
    assert r.status_code == 400
    assert "건너뛴 이유: 날짜를 읽지 못함 2줄, 합계·소계 줄 1줄, 취소 거래 1줄" in r.json()["detail"]


# ---- 11. +82 전화번호 가림 ----------------------------------------------------------------------------

@pytest.mark.parametrize("number", ["+82 10-1234-5678", "+82-10-1234-5678", "+821012345678", "821012345678",
                                    "82-10-1234-5678", "+82 (0)10 1234 5678", "+82-010-1234-5678",
                                    "010-1234-5678", "010 **** 5678"])
def test_phone_numbers_are_masked(number: str) -> None:
    assert _find_phone(f"통신요금 {number}") == "010-****-5678"


def test_plus82_line_column_is_masked() -> None:
    text = "거래일시,적요,출금액,입금액,내용,전화번호\n2026-09-01 10:00,자동이체,33000,0,SKT,+82 10 5555 1234\n"
    txns, _ = load_csv(text)
    assert txns[0].channel == Channel.TELECOM_BILL and txns[0].line_id == "010-****-1234"


# ---- 14. 취소 거래 --------------------------------------------------------------------------------------

def test_cancel_kind_is_skipped_not_flipped() -> None:
    text = ("거래일시,구분,금액,내용\n2026-09-01 10:00,출금,5000,가게\n2026-09-02 10:00,입금취소,5000,가게\n"
            "2026-09-03 10:00,출금취소,3000,가게\n2026-09-04 10:00,입금,9000,엄마\n")
    txns, report = load_csv(text)
    assert [(t.direction, t.amount) for t in txns] == [(Direction.OUT, 5000), (Direction.IN, 9000)]
    assert report["skipped_rows"] == [3, 4]
    assert any("취소로 보이는 2줄" in w for w in report["warnings"])


def test_negative_out_cell_is_cancel_unless_whole_column_is_negative() -> None:
    text = _bank(["2026-09-01 10:00,체크카드,5200,0,카페", "2026-09-02 10:00,체크카드,-5200,0,카페",
                  "2026-09-03 10:00,급여,0,100000,회사"])
    txns, report = load_csv(text)
    assert [(t.direction, t.amount) for t in txns] == [(Direction.OUT, 5200), (Direction.IN, 100_000)]
    assert "3번째 줄(취소로 보이는 음수 금액)" in " ".join(report["warnings"])
    # 출금 칸을 모두 음수로 적는 파일은 부호 표기 방식으로 보고 그대로 출금으로 읽는다
    text = _bank(["2026-09-01 10:00,체크카드,-5200,0,카페", "2026-09-02 10:00,체크카드,-3000,0,카페",
                  "2026-09-03 10:00,급여,0,100000,회사"])
    txns, report = load_csv(text)
    assert [(t.direction, t.amount) for t in txns] == [(Direction.OUT, 5200), (Direction.OUT, 3000),
                                                       (Direction.IN, 100_000)]
    assert report["skipped"] == 0


def test_cancel_word_anywhere_in_row_is_skipped() -> None:
    txns, report = load_csv(_bank(["2026-09-01 10:00,체크카드,5200,0,카페",
                                   "2026-09-02 10:00,체크카드취소,5200,0,카페"]))
    assert len(txns) == 1 and report["skipped_rows"] == [3]


# ---- 15. 금액 반올림 통일, 0원 이하 거부 -------------------------------------------------------------------

def test_standard_and_mapped_amounts_round_the_same() -> None:
    header = ",".join(synth.STANDARD_COLUMNS)
    std = f"{header}\na,2026-09-01T10:00:00,1000.5,out,card,가게,,,,\nb,2026-09-02T10:00:00,2.5,out,card,가게,,,,\n"
    assert [t.amount for t in load_csv(std)[0]] == [1001, 3]
    mapped = _bank(["2026-09-01 10:00,체크카드,1000.5,0,가게", "2026-09-02 10:00,체크카드,2.5,0,가게"])
    assert [t.amount for t in load_csv(mapped)[0]] == [1001, 3]
    assert [synth.round_amount(x) for x in (2.5, -2.5, 0.49, 1e14 + 0.5)] == [3, -3, 0, 100_000_000_000_001]


@pytest.mark.parametrize("amount", ["0", "-100", "0.4", "-0"])
def test_standard_csv_non_positive_amount_is_skipped(amount: str) -> None:
    header = ",".join(synth.STANDARD_COLUMNS)
    good = "a1,2026-09-01T10:00:00,1000,out,transfer,엄마,,,,"
    bad = f"a2,2026-09-01T11:00:00,{amount},out,transfer,엄마,,,,"
    txns, report = load_csv(f"{header}\n{good}\n{bad}\n")
    assert [t.id for t in txns] == ["a1"] and report["skipped"] == 1
    assert "3번째 줄(금액이 0원 이하)" in " ".join(report["warnings"])


def test_from_csv_rejects_non_positive_amount(tmp_path) -> None:
    path = tmp_path / "std.csv"
    path.write_text(",".join(synth.STANDARD_COLUMNS) + "\na1,2026-09-01T10:00:00,-100,out,transfer,,,,,\n",
                    encoding="utf-8")
    with pytest.raises(ValueError, match="2번째 줄.*0원 이하"):
        synth.from_csv(path)


def test_report_has_delimiter_and_warnings_avoid_banned_words() -> None:
    txns, report = load_csv(SAMPLE / "bank_export_example.csv")
    assert report["delimiter"] == ","
    banned = ("이상거래", "패턴", "탐지", "알고리즘", "모니터링", "이례", "임계", "통계")
    texts = list(report["warnings"])
    for bad in (ALL_SKIPPED, "가,나\n1,2\n"):
        with pytest.raises(LoaderError) as e:
            load_csv(bad)
        texts.append(str(e.value))
    for data in (b"PK\x03\x04", b"%PDF", b"\x89PNG\r\n\x1a\n", b"<html><table>"):
        with pytest.raises(LoaderError) as e:
            load_csv(data)
        texts.append(str(e.value))
    assert not [t for t in texts for word in banned if word in t]
