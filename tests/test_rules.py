"""detect/rules.py 테스트: 5개 시그널 룰 각각 양성·음성, 근거·관련 거래, 누수 방지."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from safepause.config import Settings
from safepause.detect.features import History, walk
from safepause.detect.rules import evaluate_rules, evaluate_rules_on
from safepause.models import Channel, Direction, RiskLevel, SignalCode, SignalHit, Transaction

OUT, IN = Direction.OUT, Direction.IN
T, CARD, MICRO, BILL = Channel.TRANSFER, Channel.CARD, Channel.MICROPAY, Channel.TELECOM_BILL
START = datetime(2026, 1, 1)
OWN_LINE = "010-****-1111"
_seq = [0]


def mk(ts: datetime, amount: int, channel: Channel = CARD, direction: Direction = OUT,
       cp: str = "", cp_id: str = "", line: str = "") -> Transaction:
    _seq[0] += 1
    return Transaction(id=f"r{_seq[0]:05d}", ts=ts, amount=amount, direction=direction,
                       channel=channel, counterparty=cp, counterparty_id=cp_id, line_id=line)


def day(d: float, hour: int = 12, minute: int = 0) -> datetime:
    return START + timedelta(days=d, hours=hour, minutes=minute)


def baseline(days: int = 60, card_base: int = 8_000, card_step: int = 2_000,
             micropay_every: int = 15) -> list[Transaction]:
    """규칙적인 정상 이력: 카드 매일, 송금 매주 5만 원, 통신요금 월 1회, 소액결제 가끔."""
    out: list[Transaction] = []
    merchants = [("편의점", "M1"), ("분식집", "M2"), ("마트", "M3")]
    for d in range(days):
        name, mid = merchants[d % 3]
        out.append(mk(day(d, 12 + d % 6), card_base + (d % 12) * card_step, CARD, OUT, name, mid))
        if d % 7 == 0:
            out.append(mk(day(d, 10), 50_000, T, OUT, "엄마", "111-222"))
        if d % 30 == 5:
            out.append(mk(day(d, 9), 55_000, BILL, OUT, "통신사", "TEL", OWN_LINE))
        if d % micropay_every == 3 % micropay_every:
            out.append(mk(day(d, 15), 3_000, MICRO, OUT, "게임", "G1", OWN_LINE))
    out.sort(key=lambda t: t.ts)
    return out


def hits_of(target: Transaction, history: list[Transaction], code: SignalCode) -> list[SignalHit]:
    return [h for h in evaluate_rules(target, history) if h.code == code]


def one_hit(target: Transaction, history: list[Transaction], code: SignalCode) -> SignalHit:
    found = hits_of(target, history, code)
    assert len(found) == 1, f"{code} 가 1건이어야 함: {found}"
    return found[0]


# ---- NIGHT_REPEAT_TRANSFER ----
class TestNightRepeatTransfer:
    code = SignalCode.NIGHT_REPEAT_TRANSFER

    def test_three_in_week_is_high(self) -> None:
        prior = [mk(day(57, 1), 100_000, T, cp="엄마", cp_id="111-222"),
                 mk(day(58, 23), 100_000, T, cp="엄마", cp_id="111-222")]
        target = mk(day(60, 2), 100_000, T, cp="엄마", cp_id="111-222")
        hit = one_hit(target, baseline() + prior, self.code)
        assert hit.severity == RiskLevel.HIGH
        assert hit.evidence["count_7d"] == 3
        assert hit.related_txn_ids == [prior[0].id, prior[1].id, target.id]

    def test_two_in_week_is_caution(self) -> None:
        prior = [mk(day(58, 23, 30), 100_000, T, cp="엄마", cp_id="111-222")]
        target = mk(day(60, 2), 100_000, T, cp="엄마", cp_id="111-222")
        hit = one_hit(target, baseline() + prior, self.code)
        assert hit.severity == RiskLevel.CAUTION
        assert hit.evidence["count_7d"] == 2

    def test_old_night_transfers_do_not_count(self) -> None:
        prior = [mk(day(50, 1), 100_000, T, cp="엄마", cp_id="111-222"),
                 mk(day(51, 2), 100_000, T, cp="엄마", cp_id="111-222")]
        target = mk(day(60, 2), 100_000, T, cp="엄마", cp_id="111-222")
        assert hits_of(target, baseline() + prior, self.code) == []

    @pytest.mark.parametrize("target", [
        mk(day(60, 14), 100_000, T, cp="엄마", cp_id="111-222"),         # 낮 시간
        mk(day(60, 6), 100_000, T, cp="엄마", cp_id="111-222"),          # 06시는 심야 아님
        mk(day(60, 2), 100_000, CARD, cp="편의점", cp_id="M1"),          # 이체 아님
        mk(day(60, 2), 100_000, T, IN, cp="엄마", cp_id="111-222"),      # 입금
    ])
    def test_negative(self, target: Transaction) -> None:
        prior = [mk(day(57, 1), 100_000, T, cp="엄마", cp_id="111-222"),
                 mk(day(58, 23), 100_000, T, cp="엄마", cp_id="111-222")]
        assert hits_of(target, baseline() + prior, self.code) == []


# ---- PAYEE_SURGE ----
class TestPayeeSurge:
    code = SignalCode.PAYEE_SURGE

    @staticmethod
    def usual(history: list[Transaction], at: datetime) -> float:
        return History(history, as_of=at).usual_7d_sum(T, OUT)

    def test_four_to_new_payee_is_high(self) -> None:
        prior = [mk(day(d), 80_000, T, cp="김철수", cp_id="999-1") for d in (57, 58, 59)]
        target = mk(day(60), 80_000, T, cp="김철수", cp_id="999-1")
        hit = one_hit(target, baseline() + prior, self.code)
        assert hit.severity == RiskLevel.HIGH
        assert hit.evidence["count_7d"] == 4
        assert hit.evidence["sum_7d"] == 320_000
        assert hit.evidence["newness_unknown"] is False
        assert hit.related_txn_ids == [p.id for p in prior] + [target.id]

    def test_four_small_to_new_payee_is_only_caution(self) -> None:
        """[변경 r2] 건수 경로의 HIGH에도 7일 합계 30만 원 하한: 1만 원 4건은 CAUTION까지만."""
        prior = [mk(day(d), 10_000, T, cp="김철수", cp_id="999-1") for d in (57, 58, 59)]
        target = mk(day(60), 10_000, T, cp="김철수", cp_id="999-1")
        hit = one_hit(target, baseline() + prior, self.code)
        assert hit.severity == RiskLevel.CAUTION
        assert hit.evidence["count_7d"] == 4 and hit.evidence["sum_7d"] == 40_000

    def test_three_small_is_caution(self) -> None:
        prior = [mk(day(d), 10_000, T, cp="김철수", cp_id="999-1") for d in (58, 59)]
        target = mk(day(60), 10_000, T, cp="김철수", cp_id="999-1")
        hit = one_hit(target, baseline() + prior, self.code)
        assert hit.severity == RiskLevel.CAUTION
        assert hit.evidence["count_7d"] == 3
        assert hit.evidence["ratio"] < 3

    def test_ratio_thresholds(self) -> None:
        hist = baseline()
        usual = self.usual(hist, day(60))
        assert 40_000 < usual < 60_000  # 매주 5만 원
        # 배율 7 한 건(35만 원): 금액 경로 CAUTION. 배율만으로 HIGH가 되려면 2건 이상이어야 함
        single = mk(day(60), int(usual * 7), T, cp="박영희", cp_id="999-2")
        hit = one_hit(single, hist, self.code)
        assert hit.severity == RiskLevel.CAUTION
        assert hit.evidence["ratio"] == pytest.approx(7, abs=0.01)
        assert hit.evidence["baseline_7d_sum"] == round(usual)
        assert hit.evidence["min_sum_7d"] == 300_000
        # 같은 새 상대에게 2건, 합계 배율 7(30만 원 이상) → HIGH
        first = mk(day(59), int(usual * 3.5), T, cp="최서연", cp_id="999-4")
        second = mk(day(60), int(usual * 3.5), T, cp="최서연", cp_id="999-4")
        hit2 = one_hit(second, hist + [first], self.code)
        assert hit2.severity == RiskLevel.HIGH and hit2.evidence["count_7d"] == 2
        # 배율 2 → 알리지 않음
        low = mk(day(60), int(usual * 2), T, cp="이민수", cp_id="999-3")
        assert hits_of(low, hist, self.code) == []

    def test_ratio_without_min_sum_is_ignored(self) -> None:
        """평소 송금이 적은 사람의 소액 1건: 배율은 커도 7일 합계 30만 원 미만이면 알리지 않음(S38)."""
        hist = baseline()
        usual = self.usual(hist, day(60))
        small = mk(day(60), int(usual * 5.5), T, cp="김철수", cp_id="999-1")  # 약 27만 원
        assert small.amount < 300_000
        assert hits_of(small, hist, self.code) == []

    def test_payee_first_seen_within_30_days_counts(self) -> None:
        prior = [mk(day(40), 10_000, T, cp="김철수", cp_id="999-1"),
                 mk(day(57), 10_000, T, cp="김철수", cp_id="999-1"),
                 mk(day(58), 10_000, T, cp="김철수", cp_id="999-1")]
        target = mk(day(60), 10_000, T, cp="김철수", cp_id="999-1")
        hit = one_hit(target, baseline() + prior, self.code)
        assert hit.evidence["first_seen_days_ago"] == pytest.approx(20.0)

    def test_long_known_payee_is_ignored(self) -> None:
        prior = [mk(day(d), 60_000, T, cp="엄마", cp_id="111-222") for d in (56, 57, 58, 59)]
        target = mk(day(60), 60_000, T, cp="엄마", cp_id="111-222")
        assert hits_of(target, baseline() + prior, self.code) == []

    def test_single_small_new_payee_is_ignored(self) -> None:
        target = mk(day(60), 50_000, T, cp="김철수", cp_id="999-1")
        assert hits_of(target, baseline(), self.code) == []

    def test_fallback_without_baseline(self) -> None:
        hit = one_hit(mk(day(0), 300_000, T, cp="김철수", cp_id="999-1"), [], self.code)
        assert hit.severity == RiskLevel.CAUTION
        assert hit.evidence["ratio"] is None and hit.evidence["baseline_7d_sum"] == 0
        assert hit.evidence["newness_unknown"] is True       # [변경 r3] 이력이 없으면 처음인지 알 수 없음
        assert hits_of(mk(day(0), 299_999, T, cp="김철수", cp_id="999-1"), [], self.code) == []

    def test_short_history_regular_family_transfer_is_not_flagged(self) -> None:
        """[변경 r2] 이력 시작 뒤 30일 안에 처음 보인 상대는 새 상대인지 알 수 없다.

        1개월치 파일의 '엄마에게 2일마다 1만 원'이 첫 거래 30일 이내 상대로 잡혀 고위험·조력자 알림이
        되던 문제(리뷰 재현). 건수 경로로는 알리지 않는다.
        """
        mom = [mk(day(2 * i), 10_000, T, cp="엄마", cp_id="900-0101") for i in range(60)]
        for i in range(3, 60):
            hist, target = mom[:i], mom[i]
            assert hits_of(target, hist, self.code) == [], f"{i}번째 송금이 걸림"

    def test_short_history_big_sum_is_caution_at_most(self) -> None:
        """이력이 짧아 새 상대인지 모를 때도 금액 경로(7일 30만 원 이상)는 CAUTION으로 알린다."""
        prior = [mk(day(d), 150_000, T, cp="김철수", cp_id="999-1") for d in (1, 2, 3)]
        target = mk(day(4), 150_000, T, cp="김철수", cp_id="999-1")
        hit = one_hit(target, prior, self.code)
        assert hit.severity == RiskLevel.CAUTION
        assert hit.evidence["newness_unknown"] is True and hit.evidence["sum_7d"] == 600_000

    def test_new_payee_after_first_30_days_can_be_high(self) -> None:
        """이력이 30일을 넘은 뒤 처음 보인 상대는 새 상대로 본다(합성 평가의 시나리오 경우)."""
        hist = [mk(day(d), 10_000, T, cp="엄마", cp_id="900-0101") for d in range(0, 40, 2)]
        prior = [mk(day(d), 100_000, T, cp="김철수", cp_id="999-1") for d in (40, 41, 42)]
        target = mk(day(43), 100_000, T, cp="김철수", cp_id="999-1")
        hit = one_hit(target, hist + prior, self.code)
        assert hit.severity == RiskLevel.HIGH and hit.evidence["newness_unknown"] is False

    def test_card_is_not_payee_surge(self) -> None:
        prior = [mk(day(d), 10_000, CARD, cp="김철수", cp_id="999-1") for d in (57, 58, 59)]
        target = mk(day(60), 10_000, CARD, cp="김철수", cp_id="999-1")
        assert hits_of(target, baseline() + prior, self.code) == []


# ---- MICROPAY_SURGE ----
class TestMicropaySurge:
    code = SignalCode.MICROPAY_SURGE

    @staticmethod
    def burst(n: int) -> list[Transaction]:
        return [mk(day(54, 10) + timedelta(hours=12 * i), 20_000, MICRO, cp="게임", line=OWN_LINE)
                for i in range(n)]

    def test_eight_in_week_is_high(self) -> None:
        target = mk(day(60, 12), 20_000, MICRO, cp="게임", line=OWN_LINE)
        hit = one_hit(target, baseline() + self.burst(7), self.code)
        assert hit.severity == RiskLevel.HIGH
        assert hit.evidence["count_7d"] == 8
        assert hit.evidence["threshold"] == 5
        assert len(hit.related_txn_ids) == 8

    def test_five_in_week_is_caution(self) -> None:
        target = mk(day(60, 12), 20_000, MICRO, cp="게임", line=OWN_LINE)
        hit = one_hit(target, baseline() + self.burst(4), self.code)
        assert hit.severity == RiskLevel.CAUTION
        assert hit.evidence["count_7d"] == 5

    def test_four_in_week_is_ignored(self) -> None:
        target = mk(day(60, 12), 20_000, MICRO, cp="게임", line=OWN_LINE)
        assert hits_of(target, baseline() + self.burst(3), self.code) == []

    def test_heavy_regular_user_uses_personal_baseline(self) -> None:
        # 평소 매일 1건(7일 평균 약 7건) → 기준 약 21건. 이번 주 10건은 급증 아님
        hist = baseline(micropay_every=1)
        target = mk(day(60, 12), 20_000, MICRO, cp="게임", line=OWN_LINE)
        assert hits_of(target, hist + self.burst(9), self.code) == []

    def test_card_is_not_micropay(self) -> None:
        target = mk(day(60, 12), 20_000, CARD, cp="게임", cp_id="G1")
        burst = [mk(day(55 + i), 20_000, CARD, cp="게임", cp_id="G1") for i in range(5)]
        assert hits_of(target, baseline() + burst, self.code) == []


# ---- NEW_MERCHANT_HIGH_VALUE ----
class TestNewMerchantHighValue:
    code = SignalCode.NEW_MERCHANT_HIGH_VALUE

    def test_single_is_caution(self) -> None:
        target = mk(day(60, 14), 150_000, CARD, cp="전자상가", cp_id="NEW1")
        hit = one_hit(target, baseline(), self.code)
        assert hit.severity == RiskLevel.CAUTION
        assert hit.evidence["threshold"] == 100_000  # p95×3 보다 10만 원 하한이 큼
        assert hit.evidence["count_7d"] == 1

    def test_two_in_week_is_high(self) -> None:
        prior = [mk(day(57, 14), 120_000, CARD, cp="금은방", cp_id="NEW0")]
        target = mk(day(60, 14), 150_000, CARD, cp="전자상가", cp_id="NEW1")
        hit = one_hit(target, baseline() + prior, self.code)
        assert hit.severity == RiskLevel.HIGH
        assert hit.evidence["count_7d"] == 2
        assert hit.related_txn_ids == [prior[0].id, target.id]

    def test_old_or_small_prior_does_not_count(self) -> None:
        prior = [mk(day(50, 14), 120_000, CARD, cp="금은방", cp_id="NEW0"),   # 7일 밖
                 mk(day(58, 14), 30_000, CARD, cp="빵집", cp_id="NEW2")]      # 고액 아님
        target = mk(day(60, 14), 150_000, CARD, cp="전자상가", cp_id="NEW1")
        assert one_hit(target, baseline() + prior, self.code).severity == RiskLevel.CAUTION

    @pytest.mark.parametrize("target", [
        mk(day(60, 14), 500_000, CARD, cp="편의점", cp_id="M1"),       # 아는 가맹점
        mk(day(60, 14), 50_000, CARD, cp="전자상가", cp_id="NEW1"),    # 고액 아님
        mk(day(60, 14), 500_000, T, cp="전자상가", cp_id="NEW1"),      # 카드 아님
    ])
    def test_negative(self, target: Transaction) -> None:
        assert hits_of(target, baseline(), self.code) == []

    def test_short_history_is_caution_at_most(self) -> None:
        """[변경 r3] 이력 첫 30일 안에는 처음 가는 가게인지 알 수 없어 CAUTION까지만(newness_unknown).

        1개월치 파일의 첫 주에 치과·안경점에서 낸 큰 돈이 고위험·조력자 알림이 되던 문제(리뷰 재현).
        """
        hist = baseline(days=20)
        prior = [mk(day(12, 14), 150_000, CARD, cp="연세치과", cp_id="NEW0")]
        target = mk(day(14, 14), 120_000, CARD, cp="밝은안경", cp_id="NEW1")
        hit = one_hit(target, hist + prior, self.code)
        assert hit.severity == RiskLevel.CAUTION and hit.evidence["newness_unknown"] is True
        assert hit.evidence["count_7d"] == 1             # 알 수 없는 과거 거래는 '새 가게'로 세지 않음
        # 빈 이력(첫 거래)도 알 수 없다
        assert one_hit(target, [], self.code).evidence["newness_unknown"] is True

    def test_prior_in_first_month_does_not_count_later(self) -> None:
        prior = [mk(day(28, 14), 150_000, CARD, cp="연세치과", cp_id="NEW0")]   # 이력 첫 30일 안
        target = mk(day(33, 14), 150_000, CARD, cp="전자상가", cp_id="NEW1")    # 30일 뒤: 알 수 있음
        hit = one_hit(target, baseline() + prior, self.code)
        assert hit.severity == RiskLevel.CAUTION and hit.evidence["newness_unknown"] is False
        assert hit.evidence["count_7d"] == 1

    def test_high_spender_uses_personal_p95(self) -> None:
        hist = baseline(card_base=50_000, card_step=5_000)  # 카드 5만~10.5만 원
        p95 = History(hist, as_of=day(60)).amount_p95(CARD, OUT)
        assert p95 * 3 > 200_000
        assert hits_of(mk(day(60, 14), 200_000, CARD, cp="전자상가", cp_id="NEW1"),
                       hist, self.code) == []
        hit = one_hit(mk(day(60, 14), int(p95 * 3) + 1, CARD, cp="전자상가", cp_id="NEW1"),
                      hist, self.code)
        assert hit.evidence["ratio_vs_p95"] >= 3


# ---- MULTI_LINE_TELECOM ----
class TestMultiLineTelecom:
    code = SignalCode.MULTI_LINE_TELECOM

    def test_first_new_line_is_caution(self) -> None:
        # 본인 회선 청구(35일째) 10일 뒤 새 회선 청구
        target = mk(day(45, 9), 33_000, BILL, cp="통신사", line="010-****-2222")
        hit = one_hit(target, baseline(), self.code)
        assert hit.severity == RiskLevel.CAUTION
        assert hit.evidence["distinct_lines_30d"] == 2
        assert hit.evidence["new_lines_30d"] == 1
        assert hit.related_txn_ids == [target.id]

    def test_second_new_line_is_high(self) -> None:
        prior = [mk(day(40, 9), 33_000, BILL, cp="통신사", line="010-****-2222")]
        target = mk(day(45, 9), 44_000, BILL, cp="통신사", line="010-****-3333")
        hit = one_hit(target, baseline() + prior, self.code)
        assert hit.severity == RiskLevel.HIGH
        assert hit.evidence["distinct_lines_30d"] == 3
        assert hit.evidence["new_lines_30d"] == 2
        assert hit.related_txn_ids == [prior[0].id, target.id]

    def test_own_known_line_is_ignored(self) -> None:
        target = mk(day(65, 9), 55_000, BILL, cp="통신사", line=OWN_LINE)
        assert hits_of(target, baseline(), self.code) == []

    def test_line_change_alone_is_ignored(self) -> None:
        # 최근 30일 안에 다른 청구가 없으면 새 회선 1개만으로는 알리지 않음
        target = mk(day(70, 9), 55_000, BILL, cp="통신사", line="010-****-2222")
        assert hits_of(target, baseline(), self.code) == []

    def test_short_history_own_line_is_not_new(self) -> None:
        """이력이 30일보다 짧아도 가장 먼저 청구된 본인 회선은 새 회선으로 세지 않는다."""
        own = mk(START + timedelta(days=0, hours=9), 55_000, BILL, cp="통신사", line=OWN_LINE)
        target = mk(START + timedelta(days=20, hours=9), 33_000, BILL, cp="통신사", line="010-****-2222")
        hit = one_hit(target, [own], self.code)
        assert hit.severity == RiskLevel.CAUTION
        # [변경 r3] 대상 회선의 첫 청구도 이력 시작 뒤 30일 안이라 새 회선인지 알 수 없다(세지 않음)
        assert hit.evidence["distinct_lines_30d"] == 2 and hit.evidence["new_lines_30d"] == 0
        assert hit.evidence["newness_unknown"] is True and hit.evidence["unknown_lines_30d"] == 1
        assert hit.evidence["usual_line"] == OWN_LINE
        # [변경 r3] 같은 짧은 이력에서 회선이 3개여도 새 회선인지 알 수 없어 CAUTION까지만
        # (1개월치 파일의 휴대폰·인터넷·태블릿 요금이 고위험·조력자 알림이 되던 문제)
        second = mk(START + timedelta(days=15, hours=9), 44_000, BILL, cp="통신사", line="010-****-3333")
        hit2 = one_hit(target, [own, second], self.code)
        assert hit2.severity == RiskLevel.CAUTION and hit2.evidence["new_lines_30d"] == 0
        assert hit2.evidence["unknown_lines_30d"] == 2 and hit2.evidence["newness_unknown"] is True

    def test_line_first_billed_in_first_month_is_not_counted_as_new(self) -> None:
        """[변경 r3] 이력 첫 30일 안에 처음 청구된 회선은 뒤에도 '새 회선'으로 세지 않는다."""
        early = mk(day(20, 9), 44_000, BILL, cp="통신사", line="010-****-3333")   # 알 수 없음
        target = mk(day(45, 9), 33_000, BILL, cp="통신사", line="010-****-2222")  # 새 회선(알 수 있음)
        hit = one_hit(target, baseline() + [early], self.code)
        assert hit.severity == RiskLevel.CAUTION
        assert hit.evidence["new_lines_30d"] == 1 and hit.evidence["unknown_lines_30d"] == 1
        assert hit.evidence["newness_unknown"] is False
        assert hit.related_txn_ids == [target.id]

    def test_micropay_on_new_line_is_not_this_signal(self) -> None:
        target = mk(day(45, 9), 33_000, MICRO, cp="게임", line="010-****-2222")
        assert hits_of(target, baseline(), self.code) == []


# ---- 공통 ----
def test_normal_baseline_has_no_hits() -> None:
    txns = baseline(90)
    for idx, txn, hist in walk(txns):
        if txn.ts >= day(30):
            assert evaluate_rules_on(txn, hist) == [], txn


def test_rules_ignore_future_transactions() -> None:
    past = baseline()
    target = mk(day(60, 2), 100_000, T, cp="김철수", cp_id="999-1")
    future = [mk(day(60, 3), 100_000, T, cp="김철수", cp_id="999-1"),
              mk(day(60, 4), 100_000, T, cp="김철수", cp_id="999-1"),
              mk(day(61, 1), 100_000, T, cp="김철수", cp_id="999-1")]
    clean = evaluate_rules(target, past)
    assert evaluate_rules(target, past + future + [target]) == clean
    assert evaluate_rules(target, History(past + future)) == clean
    assert clean == []  # 첫 심야 이체 1건, 새 상대 10만 원 1건은 룰 대상 아님


def test_incremental_rules_match_naive() -> None:
    txns = baseline(50)
    txns += [mk(day(45, 1), 100_000, T, cp="김철수", cp_id="999-1"),
             mk(day(46, 2), 100_000, T, cp="김철수", cp_id="999-1"),
             mk(day(47, 3), 100_000, T, cp="김철수", cp_id="999-1"),
             mk(day(46, 13), 150_000, CARD, cp="전자상가", cp_id="NEW1"),
             mk(day(47, 13), 150_000, CARD, cp="금은방", cp_id="NEW2"),
             mk(day(44, 9), 33_000, BILL, cp="통신사", line="010-****-2222")]
    txns += [mk(day(48, 10) + timedelta(hours=i), 10_000, MICRO, cp="게임", line=OWN_LINE)
             for i in range(9)]
    txns.sort(key=lambda t: t.ts)
    settings = Settings()
    seen_codes: set[SignalCode] = set()
    for idx, txn, hist in walk(txns, settings):
        inc = evaluate_rules_on(txn, hist, txn.ts)
        assert inc == evaluate_rules(txn, txns[:idx], settings), txn.id
        seen_codes |= {h.code for h in inc}
    assert seen_codes == set(SignalCode)  # 5개 시그널 모두 한 번 이상 발생


# ---- 리뷰 반영: 0원·식별값 표기·짧은 평소 구간 ----
def test_zero_won_transactions_are_not_counted_by_rules() -> None:
    """0원 심야 이체 3건이 심야 반복(HIGH)으로 잡히던 문제(리뷰 06 재현). 0원은 룰 건수에 넣지 않는다."""
    hist = baseline()
    zeros = [mk(day(60 + k, 1), 0, T, OUT, "홍길동", "110-111-111111") for k in range(3)]
    for k, z in enumerate(zeros):
        assert evaluate_rules(z, hist + zeros[:k]) == [], z.id      # 0원 대상은 어느 룰에도 안 걸림
    real = mk(day(63, 1), 50_000, T, OUT, "홍길동", "110-111-111111")
    codes = {h.code for h in evaluate_rules(real, hist + zeros)}
    assert SignalCode.NIGHT_REPEAT_TRANSFER not in codes             # 앞선 0원 심야 이체는 세지 않음(1건)
    zero_micro = [mk(day(60, 10 + k), 0, MICRO, OUT, "게임", "G1", OWN_LINE) for k in range(7)]
    real_micro = mk(day(60, 20), 3_000, MICRO, OUT, "게임", "G1", OWN_LINE)
    assert hits_of(real_micro, hist + zero_micro, SignalCode.MICROPAY_SURGE) == []   # 전에는 8건 HIGH
    zero_bill = mk(day(40, 9), 0, BILL, cp="통신사", line="010-****-2222")
    assert evaluate_rules(zero_bill, hist) == []
    real_bill = mk(day(45, 9), 33_000, BILL, cp="통신사", line="010-****-2222")
    hit = one_hit(real_bill, hist + [zero_bill], SignalCode.MULTI_LINE_TELECOM)    # 0원 청구로 아는 회선이 되지 않음
    assert hit.evidence["distinct_lines_30d"] == 2


def test_payee_known_by_account_in_other_format() -> None:
    """엄마 계좌(111-222)를 숫자만·점으로 적어도 아는 상대(리뷰 11 재현: 전에는 PAYEE_SURGE)."""
    hist = baseline()
    for typed in ("111-222", "111222", "111.222", "111 222"):
        target = mk(day(60, 12), 300_000, T, OUT, "엄마", typed)
        assert hits_of(target, hist, SignalCode.PAYEE_SURGE) == [], typed


def test_new_merchant_uses_floor_when_baseline_span_is_short() -> None:
    """평소 구간이 7일 미만이면 p95 = 0 → 10만 원 하한(리뷰 3: 전에는 6만 원×3 = 18만 원 기준)."""
    early = [mk(START + timedelta(hours=6 * i), 60_000, CARD, cp="편의점", cp_id="M1")
             for i in range(6)]
    target = mk(START + timedelta(days=10), 150_000, CARD, cp="전자상가", cp_id="NEW1")
    hit = one_hit(target, early, SignalCode.NEW_MERCHANT_HIGH_VALUE)
    assert hit.evidence["card_p95"] == 0 and hit.evidence["threshold"] == 100_000
    assert hit.evidence["ratio_vs_p95"] is None


@pytest.mark.parametrize("typed", ["010 **** 1111", "010.****.1111", "010-1234-1111"])
def test_own_line_in_other_format_is_not_new(typed: str) -> None:
    target = mk(day(45, 9), 55_000, BILL, cp="통신사", line=typed)
    assert hits_of(target, baseline(), SignalCode.MULTI_LINE_TELECOM) == []


def test_multi_line_counts_masked_variants_once_and_keeps_display_form() -> None:
    prior = [mk(day(38, 9), 55_000, BILL, cp="통신사", line="010-1234-1111"),   # 본인 회선, 다른 표기
             mk(day(40, 9), 33_000, BILL, cp="통신사", line="010-****-2222")]
    target = mk(day(45, 9), 33_000, BILL, cp="통신사", line="010 **** 3333")
    hit = one_hit(target, baseline() + prior, SignalCode.MULTI_LINE_TELECOM)
    assert hit.evidence["distinct_lines_30d"] == 3          # 본인·2222·3333 (본인 회선 표기가 달라도 하나)
    assert hit.evidence["usual_line"] == OWN_LINE          # 근거의 평소 회선은 처음 본 표기
    assert hit.evidence["line_id"] == "010 **** 3333"
