"""로컬 JSON 저장소.

모든 데이터는 당사자 기기의 한 폴더(root)에 JSON 파일로만 저장한다(외부 전송 없음).
쓰기는 같은 폴더의 임시 파일에 먼저 쓴 뒤 ``os.replace``로 바꿔 끼운다(원자적 교체).
읽기·쓰기(특히 기록 더하기의 읽기-수정-쓰기)는 폴더별 잠금으로 줄 세운다. 잠금은 두 겹이다.
- 같은 프로세스 안(스레드): threading.RLock
- 프로세스 사이(다른 serve 창, 명령행 wipe 등): 폴더 안 빈 파일 ``.sp-store.lock``의 OS 파일 잠금
  (표준 라이브러리: Windows ``msvcrt.locking``, 그 밖 ``fcntl.flock``). 잠금 파일에는 내용이 없다.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Any, Iterator, Optional

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from safepause.models import (
    Consent,
    as_bool,
    Decision,
    Helper,
    HelperNotice,
    RiskLevel,
    Transaction,
)

CONSENT_FILE = "consent.json"
HELPERS_FILE = "helpers.json"
TRANSACTIONS_FILE = "transactions.json"
DECISIONS_FILE = "decisions.json"
NOTICES_FILE = "notices.json"

# wipe()가 지우는 파일 목록. 이 저장소가 만드는 파일은 모두 여기에 있어야 한다.
STORE_FILES: tuple[str, ...] = (
    CONSENT_FILE,
    HELPERS_FILE,
    TRANSACTIONS_FILE,
    DECISIONS_FILE,
    NOTICES_FILE,
)
# 지우는 순서: 가장 민감한 거래 기록부터(중간에 실패해도 거래가 먼저 사라지게)
WIPE_ORDER: tuple[str, ...] = (
    TRANSACTIONS_FILE,
    NOTICES_FILE,
    DECISIONS_FILE,
    HELPERS_FILE,
    CONSENT_FILE,
)

_TMP_PREFIX = ".sp-"
_TMP_SUFFIX = ".tmp"
_REPLACE_RETRIES = 5  # Windows에서 백신·색인 프로그램이 파일을 잠깐 잡는 경우 대비
LOCK_FILE = ".sp-store.lock"   # 프로세스 사이 잠금용 빈 파일(개인 데이터 없음, wipe 대상 아님)
LOCK_TIMEOUT_SEC = 10.0        # 다른 프로세스가 잠금을 이만큼 놓지 않으면 StoreError
_LOCK_POLL_SEC = 0.01

# 파일 상태 표식: (이름, 수정 시각 ns, 크기, 파일 번호). 파일이 없으면 None 자리.
FileSignature = tuple[str, Optional[int], Optional[int], Optional[int]]


class StoreError(ValueError):
    """저장 파일을 읽거나 쓸 수 없을 때(손상·형식 오류, 잠김·읽기 전용·디스크 부족)."""


class WipeIncomplete(StoreError):
    """wipe()가 일부 파일을 지우지 못했을 때. 지운 것과 남은 것을 함께 알려 준다."""

    def __init__(self, root: Path, removed: list[str], remaining: list[str]) -> None:
        self.removed = list(removed)
        self.remaining = list(remaining)
        super().__init__(
            f"일부 파일을 지우지 못했어요: {', '.join(remaining)}. "
            "다른 프로그램(다른 SafePause 창, 백신 등)이 파일을 쓰고 있을 수 있어요. "
            f"SafePause를 모두 끈 뒤 다시 지워 주세요. 폴더: {root}"
        )


class FileLock:
    """프로세스 사이 배타 잠금(표준 라이브러리만 씀). 재진입은 되지 않는다.

    같은 파일을 가리키는 다른 FileLock과는 같은 프로세스 안에서도 겹치지 않는다.
    offset: 잠글 바이트 위치. Windows는 잠근 바이트를 다른 프로세스가 읽지 못하므로, 파일 앞쪽에
    내용(예: 서버 주소)을 두려면 내용보다 뒤를 잠근다. 프로세스가 끝나면 OS가 잠금을 푼다.
    """

    def __init__(self, path: Path | str, offset: int = 0) -> None:
        self.path = Path(path)
        self.offset = offset
        self._fd: Optional[int] = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self, timeout: float = LOCK_TIMEOUT_SEC) -> bool:
        """잠그면 True, timeout초 안에 못 잠그면 False(0이면 한 번만 시도). 파일을 못 열면 OSError."""
        if self._fd is not None:
            raise RuntimeError("이미 잡은 잠금이에요.")
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        deadline = time.monotonic() + max(timeout, 0.0)
        while True:
            try:
                self._lock(fd)
            except OSError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    return False
                time.sleep(_LOCK_POLL_SEC)
                continue
            self._fd = fd
            return True

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            self._unlock(fd)
        except OSError:
            pass
        finally:
            os.close(fd)

    def write_text(self, text: str) -> None:
        """잠근 채로 파일 앞쪽 내용을 바꾼다(잠근 바이트 앞까지만)."""
        if self._fd is None:
            raise RuntimeError("잠금을 먼저 잡아야 해요.")
        data = text.encode("utf-8")
        if self.offset and len(data) >= self.offset:
            raise ValueError("내용이 잠금 위치보다 길어요.")
        os.ftruncate(self._fd, 0)
        os.lseek(self._fd, 0, os.SEEK_SET)
        os.write(self._fd, data)

    # ---- OS별 ----
    def _lock(self, fd: int) -> None:
        if os.name == "nt":
            os.lseek(fd, self.offset, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(self, fd: int) -> None:
        if os.name == "nt":
            os.lseek(fd, self.offset, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)

    def __enter__(self) -> "FileLock":
        if not self.acquire():
            raise TimeoutError(f"잠금을 잡지 못했어요: {self.path}")
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


class _FolderLock:
    """저장 폴더 하나의 잠금: 스레드 사이는 RLock, 프로세스 사이는 FileLock. 같은 스레드는 다시 들어올 수 있다."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._thread = threading.RLock()
        self._file = FileLock(root / LOCK_FILE)
        self._depth = 0

    def __enter__(self) -> "_FolderLock":
        self._thread.acquire()
        try:
            if self._depth == 0:
                self._acquire_file()
            self._depth += 1
        except BaseException:
            self._thread.release()
            raise
        return self

    def __exit__(self, exc_type: Optional[type[BaseException]], exc: Optional[BaseException],
                 tb: Optional[TracebackType]) -> None:
        try:
            self._depth -= 1
            if self._depth == 0:
                self._file.release()
        finally:
            self._thread.release()

    def _acquire_file(self) -> None:
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            got = self._file.acquire(LOCK_TIMEOUT_SEC)
        except OSError:
            # 잠금 파일을 만들 수 없는 폴더(읽기 전용 등): 읽기는 되게 두고, 쓰기는 _write가 한국어로 알린다
            return
        if not got:
            raise StoreError("다른 SafePause 창이 저장 파일을 쓰고 있어요. 잠시 뒤 다시 해 주세요. "
                             f"계속되면 SafePause 창을 모두 닫고 다시 켜 주세요. 폴더: {self._root}")


# 같은 폴더를 가리키는 Store 인스턴스끼리 잠금을 공유한다.
_locks: dict[str, _FolderLock] = {}
_locks_guard = threading.Lock()


def _lock_for(root: Path) -> _FolderLock:
    key = os.path.normcase(str(root.resolve()))
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = _FolderLock(root)
            _locks[key] = lock
        return lock


def _as_bool(value: Any) -> bool:
    """동의 값은 명확한 참일 때만 True(손으로 고친 "false" 문자열 등을 동의로 오해하지 않게)."""
    return as_bool(value)


class Store:
    """당사자 기기 안의 JSON 파일 저장소."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = _lock_for(self.root)

    @contextmanager
    def transaction(self) -> Iterator["Store"]:
        """여러 번의 읽기·쓰기를 한 덩어리로 묶는다(프로세스 사이 폴더 잠금을 그동안 쥔다).

        안쪽의 load/save도 같은 잠금을 다시 잡으므로(재진입) 그대로 쓸 수 있다. 예: 안전 정지 결정은
        동의 확인 → 거래 이력 → 결정 기록 → 조력자 알림 기록을 이 안에서 해서, 그 사이에 다른 창·명령행이
        '모두 지우기'를 해도 지운 거래가 되살아나지 않게 한다.
        """
        with self._lock:
            yield self

    # ---- 동의 ----
    def load_consent(self) -> Consent:
        data = self._read(CONSENT_FILE)
        if data is None:
            return Consent()
        if not isinstance(data, dict):
            raise self._broken(CONSENT_FILE)
        return Consent(
            monitoring=_as_bool(data.get("monitoring")),
            helper_alerts=_as_bool(data.get("helper_alerts")),
            counseling_referral=_as_bool(data.get("counseling_referral")),
            given_by=str(data.get("given_by", "self") or "self"),
            updated_at=str(data.get("updated_at", "") or ""),
        )

    def save_consent(self, consent: Consent) -> None:
        self._write(CONSENT_FILE, consent.to_dict())

    # ---- 신뢰 조력자 ----
    def load_helpers(self) -> list[Helper]:
        rows = self._read_list(HELPERS_FILE)
        try:
            return [Helper.from_dict(r) for r in rows]
        except (KeyError, TypeError, ValueError) as exc:
            raise self._broken(HELPERS_FILE) from exc

    def save_helpers(self, helpers: list[Helper]) -> None:
        self._write(HELPERS_FILE, [h.to_dict() for h in helpers])

    # ---- 거래 ----
    def load_transactions(self) -> list[Transaction]:
        rows = self._read_list(TRANSACTIONS_FILE)
        try:
            return [Transaction.from_dict(r) for r in rows]
        except (KeyError, TypeError, ValueError) as exc:
            raise self._broken(TRANSACTIONS_FILE) from exc

    def save_transactions(self, txns: list[Transaction]) -> None:
        self._write(TRANSACTIONS_FILE, [t.to_dict() for t in txns])

    # ---- 안전 정지 결정 기록 ----
    def append_decision(
        self, txn_id: str, decision: Decision | str, level: RiskLevel | str, at: str,
        *, asked: Optional[int] = None,
    ) -> None:
        """결정 1건을 기록한다. asked: '조력자에게 물어볼래요'로 실제 물어본 조력자 수(선택)."""
        record: dict[str, Any] = {
            "txn_id": str(txn_id),
            "decision": Decision(decision).value,
            "level": RiskLevel(level).value,
            "at": str(at),
        }
        if asked is not None:
            record["asked"] = int(asked)
        self._append(DECISIONS_FILE, record)

    def load_decisions(self) -> list[dict[str, Any]]:
        return self._read_records(DECISIONS_FILE)

    # ---- 조력자 알림 기록(실제 발송 없음) ----
    def append_notice(self, notice: HelperNotice) -> None:
        self._append(NOTICES_FILE, notice.to_dict())

    def load_notices(self) -> list[dict[str, Any]]:
        return self._read_records(NOTICES_FILE)

    # ---- 즉시 철회권 ----
    def wipe(self) -> list[str]:
        """저장한 데이터를 모두 지운다. 지운 파일 이름 목록을 돌려준다.

        거래 기록부터 지우고, 파일 하나를 지우지 못해도 나머지를 계속 지운다.
        하나라도 남으면 WipeIncomplete(한국어 안내, 남은 파일 목록)를 낸다.
        """
        removed: list[str] = []
        remaining: list[str] = []
        with self._lock:
            if not self.root.exists():
                return removed
            names = [*WIPE_ORDER, *(n for n in STORE_FILES if n not in WIPE_ORDER)]
            # 중단된 쓰기로 남은 임시 파일도 지운다(내용이 거래 기록일 수 있음).
            names += sorted(p.name for p in self.root.glob(f"{_TMP_PREFIX}*{_TMP_SUFFIX}"))
            for name in names:
                try:
                    if self._unlink(self.root / name):
                        removed.append(name)
                except OSError:
                    remaining.append(name)
        if remaining:
            raise WipeIncomplete(self.root, removed, remaining)
        return removed

    def signature(self, name: str = TRANSACTIONS_FILE) -> FileSignature:
        """파일이 바뀌었는지 알아보는 표식. 다른 프로세스가 고치거나 지운 것도 알아챈다."""
        try:
            st = self._path(name).stat()
        except FileNotFoundError:
            return (name, None, None, None)
        return (name, st.st_mtime_ns, st.st_size, st.st_ino)

    # ---- 내부 ----
    @staticmethod
    def _unlink(path: Path) -> bool:
        """파일을 지운다(잠깐 잠긴 경우 몇 번 다시 시도). 없으면 False."""
        for attempt in range(_REPLACE_RETRIES):
            try:
                path.unlink()
                return True
            except FileNotFoundError:
                return False
            except PermissionError:
                if attempt == _REPLACE_RETRIES - 1:
                    raise
                time.sleep(0.05 * (attempt + 1))
        return False

    def _path(self, name: str) -> Path:
        return self.root / name

    def _broken(self, name: str) -> StoreError:
        return StoreError(f"저장 파일을 읽을 수 없어요(손상되었을 수 있어요): {self._path(name)}")

    def _read(self, name: str) -> Any:
        path = self._path(name)
        with self._lock:
            if not path.exists():
                return None
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise self._broken(name) from exc
            except FileNotFoundError:  # 확인한 뒤 다른 프로세스가 지운 경우
                return None
            except OSError as exc:  # 잠김·권한 없음 등
                raise StoreError("저장 파일을 열 수 없어요. 다른 프로그램(백신 등)이 쓰고 있을 수 있어요. "
                                 f"잠시 뒤 다시 해 주세요. 파일: {path}") from exc
        if not text.strip():
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise self._broken(name) from exc

    def _read_list(self, name: str) -> list[Any]:
        data = self._read(name)
        if data is None:
            return []
        if not isinstance(data, list):
            raise self._broken(name)
        return data

    def _read_records(self, name: str) -> list[dict[str, Any]]:
        """기록 목록(결정·알림): 원소가 모두 {…}여야 한다(손상 파일을 한국어 안내로 알림, 500 방지)."""
        rows = self._read_list(name)
        if any(not isinstance(r, dict) for r in rows):
            raise self._broken(name)
        return rows

    def _append(self, name: str, record: dict[str, Any]) -> None:
        with self._lock:
            rows = self._read_list(name)
            rows.append(record)
            self._write(name, rows)

    def _cannot_write(self, name: str) -> StoreError:
        return StoreError(
            "저장 파일을 쓸 수 없어요. 다른 프로그램(백신 등)이 파일을 쓰고 있거나, 읽기 전용이거나, "
            f"디스크가 가득 찼을 수 있어요. 잠시 뒤 다시 해 주세요. 파일: {self._path(name)}"
        )

    def _write(self, name: str, obj: Any) -> None:
        """임시 파일에 쓴 뒤 바꿔 끼운다. 파일 시스템 오류(OSError)는 한국어 StoreError로 바꾼다."""
        payload = json.dumps(obj, ensure_ascii=False, indent=2)
        with self._lock:
            try:
                self.root.mkdir(parents=True, exist_ok=True)
                fd, tmp_name = tempfile.mkstemp(prefix=_TMP_PREFIX, suffix=_TMP_SUFFIX, dir=self.root)
            except OSError as exc:
                raise self._cannot_write(name) from exc
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                    f.write(payload)
                    f.flush()
                    os.fsync(f.fileno())
                self._replace(Path(tmp_name), self._path(name))
            except BaseException as exc:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                if isinstance(exc, OSError):
                    raise self._cannot_write(name) from exc
                raise

    @staticmethod
    def _replace(src: Path, dst: Path) -> None:
        for attempt in range(_REPLACE_RETRIES):
            try:
                os.replace(src, dst)
                return
            except PermissionError:
                if attempt == _REPLACE_RETRIES - 1:
                    raise
                time.sleep(0.05 * (attempt + 1))
