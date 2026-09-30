@echo off
rem CRLF line endings required. (.gitattributes: *.bat text eol=crlf) LF endings break cmd.exe parsing.
chcp 65001 >nul
setlocal
rem SafePause.exe 빌드: PyInstaller onefile. 결과는 dist\SafePause.exe
rem 가상환경 .venv 를 쓰고, 없으면 만든다. 빌드에는 인터넷으로 패키지 설치가 필요하다.

cd /d "%~dp0.."

rem 압축을 풀지 않고 실행했거나 bat만 복사한 경우: 원인을 알리고 멈춘다(쓸모없는 .venv를 만들지 않게)
if not exist "requirements.txt" goto :not_extracted
if not exist "safepause\__init__.py" goto :not_extracted
set "HERE=%CD%"
set "PY=.venv\Scripts\python.exe"
if not "%HERE:~100,1%"=="" echo [SafePause] 알림: 폴더 경로가 길어요. 빌드가 실패하면 C:\SafePause 같은 짧은 폴더로 옮겨 다시 실행해 주세요.

if exist "%PY%" goto :have_venv
echo [SafePause] 가상환경 .venv 를 만듭니다...
call :make_venv
if not exist "%PY%" goto :no_python

:have_venv
"%PY%" -c "import sys" >nul 2>nul
if errorlevel 1 goto :broken_venv
"%PY%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 goto :old_python

echo [SafePause] 필요한 패키지와 PyInstaller를 설치합니다...
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt "pyinstaller>=6,<7"
if errorlevel 1 goto :fail

echo [SafePause] SafePause.exe 를 빌드합니다. 몇 분 걸릴 수 있어요...
"%PY%" -m PyInstaller --noconfirm --clean --distpath dist --workpath build\pyinstaller packaging\safepause.spec
if errorlevel 1 goto :fail

echo [SafePause] 완료: %CD%\dist\SafePause.exe
exit /b 0

:make_venv
where py >nul 2>nul
if errorlevel 1 goto :venv_with_python
py -3 -m venv .venv
goto :eof
:venv_with_python
python -m venv .venv
goto :eof

:no_python
echo [SafePause] Python 3.10 이상을 찾지 못했어요. python.org 에서 설치한 뒤 다시 실행해 주세요.
exit /b 1

:broken_venv
echo [SafePause] .venv 폴더의 Python을 실행하지 못했어요. .venv 폴더를 지우고 다시 실행해 주세요.
exit /b 1

:old_python
echo [SafePause] Python 3.10 이상이 필요해요. .venv 폴더를 지우고 새 Python으로 다시 실행해 주세요.
exit /b 1

:fail
echo [SafePause] 빌드에 실패했어요. 위의 오류 메시지를 확인해 주세요. 폴더 경로가 길면 짧은 폴더로 옮겨 다시 해 보세요.
exit /b 1

:not_extracted
echo [SafePause] 소스 폴더에 requirements.txt 또는 safepause 폴더가 없어요.
echo [SafePause] 압축을 먼저 모두 푼 뒤, 푼 폴더의 packaging\build_exe.bat를 실행해 주세요.
exit /b 1
