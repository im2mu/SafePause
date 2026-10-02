"""SafePause APK 빌드(Gradle 없이 안드로이드 SDK 명령어만 사용).

순서: aapt2 compile/link(리소스·매니페스트·assets) → javac → d8(dex) → zip에 dex 추가
      → zipalign → apksigner 서명·검증.

필요한 것(모두 공식 배포본): JDK 17 이상, Android build-tools 35, platforms/android-35.
    python android/build_apk.py --sdk <SDK 폴더> --jdk <JDK 폴더> --www <assets/www 폴더> --out SafePause.apk

서명 키: --keystore를 주지 않으면 android/signing/release.jks를 쓰고, 없으면 새로 만든다.
키 비밀번호는 같은 폴더의 keystore.properties에 적는다(저장소에 올리지 않음, .gitignore).
같은 키로 서명해야 기기에 설치된 앱을 지우지 않고 새 버전으로 업데이트할 수 있다.
"""
from __future__ import annotations

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MIN_SDK = 26
TARGET_SDK = 35
# 이미 압축된 파일은 다시 압축하지 않는다(빌드 시간·읽기 속도)
NO_COMPRESS = ("whl", "zip", "png", "woff2")


def run(cmd: list[str], **kw) -> None:
    print("  $", " ".join(str(c) for c in cmd[:6]), "..." if len(cmd) > 6 else "")
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def tool(sdk: Path, name: str) -> Path:
    bt = sdk / "build-tools" / "35.0.0"
    for cand in (bt / f"{name}.exe", bt / f"{name}.bat", bt / name):
        if cand.exists():
            return cand
    raise SystemExit(f"build-tools에서 {name}을 찾지 못했어요: {bt}")


def ensure_keystore(jdk: Path, ks: Path) -> tuple[Path, str]:
    props = ks.with_name("keystore.properties")
    if ks.exists() and props.exists():
        values = dict(line.split("=", 1) for line in props.read_text("utf-8").splitlines() if "=" in line)
        return ks, values["storePassword"].strip()
    ks.parent.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(24)
    run([jdk / "bin" / "keytool", "-genkeypair", "-keystore", ks, "-storetype", "PKCS12",
         "-alias", "safepause", "-keyalg", "RSA", "-keysize", "3072", "-validity", "10000",
         "-storepass", password, "-keypass", password,
         "-dname", "CN=SafePause, OU=SafePause, O=SafePause, C=KR"])
    props.write_text(f"storeFile={ks.name}\nkeyAlias=safepause\nstorePassword={password}\n", "utf-8")
    print(f"  새 서명 키를 만들었어요: {ks} (비밀번호는 {props.name})")
    return ks, password


def build(sdk: Path, jdk: Path, www: Path, out: Path, *, debug: bool, version_code: int,
          version_name: str, keystore: Path) -> Path:
    android_jar = sdk / "platforms" / "android-35" / "android.jar"
    if not android_jar.exists():
        raise SystemExit(f"android.jar가 없어요: {android_jar}")
    if not (www / "index.html").exists():
        raise SystemExit(f"assets/www에 index.html이 없어요: {www}")
    aapt2, d8, zipalign, apksigner = (tool(sdk, n) for n in ("aapt2", "d8", "zipalign", "apksigner"))
    env = {**os.environ, "JAVA_HOME": str(jdk), "PATH": str(jdk / "bin") + os.pathsep + os.environ.get("PATH", "")}

    with tempfile.TemporaryDirectory(prefix="spbuild-") as tmp:
        t = Path(tmp)
        # assets는 www를 통째로 담는다(aapt2 -A는 폴더 이름 그대로 담으므로 assets/www 구조로 복사)
        assets = t / "assets"
        shutil.copytree(www, assets / "www")

        print("[1/6] 리소스 컴파일")
        run([aapt2, "compile", "--dir", HERE / "res", "-o", t / "res.zip"])

        print("[2/6] 리소스·매니페스트·assets 연결")
        link = [aapt2, "link", "-o", t / "base.apk", "-I", android_jar,
                "--manifest", HERE / "AndroidManifest.xml", "-A", assets,
                "--min-sdk-version", MIN_SDK, "--target-sdk-version", TARGET_SDK,
                "--version-code", version_code, "--version-name", version_name,
                "--auto-add-overlay"]
        for ext in NO_COMPRESS:
            link += ["-0", ext]
        if debug:
            link.append("--debug-mode")
        link.append(t / "res.zip")
        run(link)

        print("[3/6] 자바 컴파일")
        classes = t / "classes"
        classes.mkdir()
        sources = sorted(str(p) for p in (HERE / "src").rglob("*.java"))
        run([jdk / "bin" / "javac", "-encoding", "UTF-8", "--release", "11", "-classpath", android_jar,
             "-d", classes, "-Xlint:-options", *sources], env=env)

        print("[4/6] dex 변환(d8)")
        dex_out = t / "dex"
        dex_out.mkdir()
        class_files = [str(p) for p in classes.rglob("*.class")]
        run([d8, "--release" if not debug else "--debug", "--min-api", MIN_SDK, "--lib", android_jar,
             "--output", dex_out, *class_files], env=env)

        print("[5/6] APK 묶기·정렬")
        unsigned = t / "unsigned.apk"
        shutil.copy(t / "base.apk", unsigned)
        with zipfile.ZipFile(unsigned, "a", zipfile.ZIP_DEFLATED) as z:
            z.write(dex_out / "classes.dex", "classes.dex")
        aligned = t / "aligned.apk"
        run([zipalign, "-P", "16", "-f", "4", unsigned, aligned])

        print("[6/6] 서명·검증")
        ks, password = ensure_keystore(jdk, keystore)
        out.parent.mkdir(parents=True, exist_ok=True)
        run([apksigner, "sign", "--ks", ks, "--ks-key-alias", "safepause",
             "--ks-pass", f"pass:{password}", "--key-pass", f"pass:{password}",
             "--v1-signing-enabled", "false", "--v2-signing-enabled", "true", "--v3-signing-enabled", "true",
             "--out", out, aligned], env=env)
        run([apksigner, "verify", "--min-sdk-version", MIN_SDK, out], env=env)
    idsig = out.with_name(out.name + ".idsig")
    if idsig.exists():
        idsig.unlink()
    print(f"완료: {out} ({out.stat().st_size / 1e6:.1f} MB)")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sdk", type=Path, required=True)
    ap.add_argument("--jdk", type=Path, required=True)
    ap.add_argument("--www", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--debug", action="store_true", help="디버그 빌드(WebView 원격 디버깅·로그 켜짐)")
    ap.add_argument("--version-code", type=int, default=3)
    ap.add_argument("--version-name", default="0.3.0")
    ap.add_argument("--keystore", type=Path, default=HERE / "signing" / "release.jks")
    a = ap.parse_args(argv)
    build(a.sdk, a.jdk, a.www, a.out, debug=a.debug, version_code=a.version_code,
          version_name=a.version_name, keystore=a.keystore)
    return 0


if __name__ == "__main__":
    sys.exit(main())
