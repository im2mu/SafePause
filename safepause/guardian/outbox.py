"""조력자 알림 보관함. SPEC §7.

프로토타입이므로 실제 문자·메일·앱 알림을 보내지 않는다. 알림은 로컬 저장소에 기록만 된다.
"""
from __future__ import annotations

from typing import Iterable, Protocol, runtime_checkable

from safepause.models import HelperNotice, NotifyPlan

DELIVERY_NOTE = "알림은 기록만 해요. 이 기기에 적어 두고, 문자나 메일은 보내지 않아요."


@runtime_checkable
class NoticeStore(Protocol):
    """Outbox가 쓰는 저장소 기능(store.Store가 제공)."""

    def append_notice(self, notice: HelperNotice) -> None: ...


class Outbox:
    """HelperNotice를 저장소에 기록한다. 외부로 아무것도 보내지 않는다."""

    delivery_note = DELIVERY_NOTE

    def __init__(self, store: NoticeStore) -> None:
        if not callable(getattr(store, "append_notice", None)):
            raise TypeError("store에는 append_notice(notice) 메서드가 있어야 해요.")
        self._store = store

    def send(self, notice: HelperNotice) -> None:
        """알림 한 건을 기록한다(실제 발송 없음)."""
        if not isinstance(notice, HelperNotice):
            raise TypeError("HelperNotice만 기록할 수 있어요.")
        self._store.append_notice(notice)

    def send_all(self, notices: Iterable[HelperNotice]) -> int:
        """여러 건을 순서대로 기록하고 기록한 건수를 돌려준다."""
        count = 0
        for notice in notices:
            self.send(notice)
            count += 1
        return count

    def send_plan(self, plan: NotifyPlan) -> int:
        """policy.decide() 결과의 알림을 모두 기록한다."""
        return self.send_all(plan.notices)


__all__ = ["DELIVERY_NOTE", "NoticeStore", "Outbox"]
