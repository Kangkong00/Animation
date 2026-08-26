@echo off
REM ===========================================================================
REM  캡컷 드래프트 만들기 (윈도우)
REM  이 파일을 더블클릭하면 됩니다. 검은 창에 뭘 칠 필요 없습니다.
REM ===========================================================================
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title 캡컷 드래프트 만들기

echo.
echo ==========================================================
echo   캡컷 드래프트 만들기
echo ==========================================================
echo.

REM ── 1. 파이썬 찾기 ────────────────────────────────────────────────────────
set PY=
python --version >nul 2>&1 && set PY=python
if not defined PY ( py -3 --version >nul 2>&1 && set PY=py -3 )
if not defined PY ( python3 --version >nul 2>&1 && set PY=python3 )

if not defined PY (
    echo   [문제] 이 컴퓨터에 파이썬이 없습니다.
    echo.
    echo   해결 방법:
    echo     1. https://www.python.org/downloads/  에 들어가서
    echo     2. 노란 Download 버튼을 눌러 설치하세요
    echo     3. 설치 화면 맨 아래 "Add Python to PATH" 에 꼭 체크하세요
    echo     4. 설치가 끝나면 이 파일을 다시 더블클릭하세요
    echo.
    echo   회사 보안 때문에 설치가 막히면, 개인 노트북에서 하시면 됩니다.
    echo.
    pause
    exit /b 1
)
echo   파이썬 확인 완료.

REM ── 2. 필요한 부품(pycapcut) 확인 ─────────────────────────────────────────
%PY% -c "import pycapcut" >nul 2>&1
if errorlevel 1 (
    echo   부품을 내려받는 중입니다. 처음 한 번만 걸립니다...
    %PY% -m pip install pycapcut >nul 2>&1
    if errorlevel 1 (
        echo   다시 시도하는 중...
        %PY% -m pip install --user pycapcut
    )
    %PY% -c "import pycapcut" >nul 2>&1
    if errorlevel 1 (
        echo.
        echo   [문제] 부품을 내려받지 못했습니다.
        echo   회사 보안이 인터넷 내려받기를 막고 있을 수 있습니다.
        echo   개인 노트북에서 다시 해보세요.
        echo.
        pause
        exit /b 1
    )
)
echo   부품 확인 완료.
echo.

REM ── 3. 실행 ───────────────────────────────────────────────────────────────
%PY% make_capcut_draft.py
if errorlevel 1 (
    echo.
    echo   위에 빨간 글씨로 이유가 적혀 있습니다. 그대로 복사해서 물어보세요.
)

echo.
echo   창을 닫으려면 아무 키나 누르세요.
pause >nul
