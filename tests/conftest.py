"""pytest 공통 설정: 시험 표시(marker) 등록."""


def pytest_configure(config) -> None:
    # 긴 퍼징(tests/test_loader_fuzz.py::test_fuzz_long). 기본 실행에서는 건너뛰고 -m fuzz_long으로 돌린다
    config.addinivalue_line("markers", "fuzz_long: 오래 걸리는 파일 읽기 퍼징(pytest -m fuzz_long으로 실행)")
