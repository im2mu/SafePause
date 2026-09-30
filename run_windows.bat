@echo off
rem CRLF line endings required. (.gitattributes: *.bat text eol=crlf) LF endings break cmd.exe parsing.
chcp 65001 >nul
setlocal
rem SafePause 소스 실행(Windows). 처음 한 번은 가상환경 .venv 를 만들고 패키지를 설치한다.
rem 그다음부터는 바로 로컬 서버를 열고 브라우저로 화면을 띄운다.
rem 추가 인자는 serve 명령에 그대로 넘긴다. 예: run_windows.bat --port 9000 --no-browser

cd /d "%~dp0"

rem 압축을 풀지 않고 실행했거나 bat만 복사한 경우: 원인을 알리고 멈춘다(쓸모없는 .venv를 만들지 않게)
if not exist "requirements.txt" goto :not_extracted
if not exist "safepause\__init__.py" goto :not_extracted
set "HERE=%~dp0"
set "PY=.venv\Scripts\python.exe"
set "MARK=.venv\.safepause-installed"

rem 경로가 100자를 넘으면 경고: Windows 기본 설정(긴 경로 꺼짐)에서는 패키지 설치가 실패할 수 있다.
if not "%HERE:~100,1%"=="" echo [SafePause] 알림: 폴더 경로가 길어요. 설치나 실행이 실패하면 C:\SafePause 같은 짧은 폴더로 옮겨 다시 실행해 주세요.

if exist "%MARK%" goto :run

echo [SafePause] 처음 실행 준비: 가상환경을 만들고 필요한 패키지를 설치합니다.
echo [SafePause] 인터넷 연결이 필요하고, 몇 분 걸릴 수 있어요.
if not exist "%PY%" call :make_venv
if not exist "%PY%" goto :no_python

"%PY%" -c "import sys" >nul 2>nul
if errorlevel 1 goto :broken_venv
"%PY%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 goto :old_python

"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 goto :install_failed
echo installed> "%MARK%"

:run
"%PY%" -c "import sys" >nul 2>nul
if errorlevel 1 goto :broken_venv
echo [SafePause] 서버를 시작합니다. 끝내려면 이 창에서 Ctrl+C 를 누르세요.
"%PY%" -m safepause serve %*
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" pause
exit /b %CODE%

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
pause
exit /b 1

:broken_venv
echo [SafePause] .venv 폴더의 Python을 실행하지 못했어요. 다른 컴퓨터에서 복사된 .venv 폴더일 수 있어요.
echo [SafePause] .venv 폴더를 지우고 다시 실행해 주세요.
pause
exit /b 1

:old_python
echo [SafePause] Python 3.10 이상이 필요해요. .venv 폴더를 지우고 새 Python으로 다시 실행해 주세요.
pause
exit /b 1

:install_failed
echo [SafePause] 패키지 설치에 실패했어요. 인터넷 연결을 확인해 주세요.
echo [SafePause] 폴더 경로가 너무 길어도 설치가 실패할 수 있어요. C:\SafePause 같은 짧은 폴더로 옮기고 .venv 폴더를 지운 뒤 다시 실행해 주세요.
pause
exit /b 1

:not_extracted
echo [SafePause] 이 폴더에 requirements.txt 또는 safepause 폴더가 없어요.
echo [SafePause] 압축을 먼저 모두 푼 뒤, 푼 폴더에서 run_windows.bat를 실행해 주세요.
pause
exit /b 1
