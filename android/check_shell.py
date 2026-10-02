"""안드로이드 셸(MainActivity)의 순수 자바 부분을 PC의 JVM에서 시험한다(에뮬레이터 없이).

    python android/check_shell.py --sdk <SDK 폴더> --jdk <JDK 폴더>

MainActivity와 android/check/ShellCheck.java를 android.jar에 맞춰 컴파일하고 ShellCheck를 돌린다.
android.jar의 안드로이드 클래스는 껍데기라 실행하면 오류가 나므로, 시험은 안드로이드 API를 쓰지 않는
부분(TTS 발화 id 비교, 문자·메일 주소 길이, 앱 이름 정리·순서)만 다룬다. 시험 코드는 APK에 들어가지 않는다.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sdk", type=Path, required=True)
    ap.add_argument("--jdk", type=Path, required=True)
    a = ap.parse_args(argv)
    android_jar = a.sdk / "platforms" / "android-35" / "android.jar"
    if not android_jar.exists():
        raise SystemExit(f"android.jar가 없어요: {android_jar}")
    sources = sorted(str(p) for p in (HERE / "src").rglob("*.java"))
    sources += sorted(str(p) for p in (HERE / "check").rglob("*.java"))
    with tempfile.TemporaryDirectory(prefix="spcheck-") as tmp:
        subprocess.run([str(a.jdk / "bin" / "javac"), "-encoding", "UTF-8", "--release", "11",
                        "-classpath", str(android_jar), "-d", tmp, "-Xlint:-options", *sources], check=True)
        cp = os.pathsep.join([tmp, str(android_jar)])
        r = subprocess.run([str(a.jdk / "bin" / "java"), "-Dfile.encoding=UTF-8", "-Dstdout.encoding=UTF-8",
                            "-cp", cp, "kr.safepause.mobile.ShellCheck"])
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
