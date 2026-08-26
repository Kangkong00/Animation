@echo off
REM ===========================================================================
REM  캡컷 드래프트 만들기 (윈도우)
REM  이 파일을 더블클릭하면 됩니다.
REM
REM  파이썬이 PATH 에 등록돼 있지 않아도(회사 PC 에서 흔함) 깔린 자리를
REM  직접 뒤져서 찾아냅니다. 그래도 못 찾으면 어디를 뒤졌는지 다 보여 줍니다.
REM ===========================================================================
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title 캡컷 드래프트 만들기

echo.
echo ==========================================================
echo   캡컷 드래프트 만들기
echo ==========================================================
echo.

REM ── 0. 프로그램이 같은 폴더에 있는지 ──────────────────────────────────────
if not exist "make_capcut_draft.py" goto NOPROGRAM
echo   [1/4] 프로그램 확인 완료.

REM ── 1. 파이썬 찾기 ────────────────────────────────────────────────────────
REM  (1) 이름으로 찾기 — PATH 에 등록돼 있는 경우
set PYCMD=
py -3 --version >nul 2>&1
if not errorlevel 1 set PYCMD=py -3
if defined PYCMD goto GOTPY

python --version >nul 2>&1
if not errorlevel 1 set PYCMD=python
if defined PYCMD goto GOTPY

python3 --version >nul 2>&1
if not errorlevel 1 set PYCMD=python3
if defined PYCMD goto GOTPY

REM  (2) 깔린 자리를 직접 뒤지기 — PATH 에 등록이 안 된 경우
for /d %%P in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%~P\python.exe" set PYCMD="%%~P\python.exe"
for /d %%P in ("%PROGRAMFILES%\Python3*") do if exist "%%~P\python.exe" set PYCMD="%%~P\python.exe"
for /d %%P in ("%PROGRAMFILES(X86)%\Python3*") do if exist "%%~P\python.exe" set PYCMD="%%~P\python.exe"
for /d %%P in ("C:\Python3*") do if exist "%%~P\python.exe" set PYCMD="%%~P\python.exe"
if exist "%USERPROFILE%\anaconda3\python.exe" set PYCMD="%USERPROFILE%\anaconda3\python.exe"
if exist "%USERPROFILE%\miniconda3\python.exe" set PYCMD="%USERPROFILE%\miniconda3\python.exe"
if exist "%LOCALAPPDATA%\anaconda3\python.exe" set PYCMD="%LOCALAPPDATA%\anaconda3\python.exe"
if exist "%LOCALAPPDATA%\Continuum\anaconda3\python.exe" set PYCMD="%LOCALAPPDATA%\Continuum\anaconda3\python.exe"
if exist "C:\ProgramData\Anaconda3\python.exe" set PYCMD="C:\ProgramData\Anaconda3\python.exe"

if not defined PYCMD goto NOPYTHON

REM  찾은 게 진짜 돌아가는지 확인 (윈도우 스토어 가짜 파이썬 걸러내기)
%PYCMD% --version >nul 2>&1
if errorlevel 1 goto NOPYTHON

:GOTPY
echo   [2/4] 파이썬 확인 완료.
%PYCMD% --version
echo.

REM ── 2. 필요한 부품(pycapcut) 확인 ─────────────────────────────────────────
%PYCMD% -c "import pycapcut" >nul 2>&1
if not errorlevel 1 goto GOTLIB

echo   [3/4] 부품을 내려받는 중입니다. 처음 한 번만 걸립니다...
%PYCMD% -m pip install pycapcut >nul 2>&1
%PYCMD% -c "import pycapcut" >nul 2>&1
if not errorlevel 1 goto GOTLIB

echo         다시 시도하는 중...
%PYCMD% -m pip install --user pycapcut
%PYCMD% -c "import pycapcut" >nul 2>&1
if errorlevel 1 goto NOLIB

:GOTLIB
echo   [3/4] 부품 확인 완료.
echo.
echo   [4/4] 시작합니다.
echo.

REM ── 3. 실행 ───────────────────────────────────────────────────────────────
%PYCMD% make_capcut_draft.py
if errorlevel 1 (
    echo.
    echo   위에 이유가 적혀 있습니다. 그대로 사진 찍어 물어보세요.
)
goto END


REM ===========================================================================
:NOPROGRAM
echo   [문제] 이 폴더에 프로그램 파일이 없습니다.
echo.
echo   지금 폴더: %CD%
echo.
echo   압축을 풀고 나온 폴더 "안으로" 들어가서, make_capcut_draft.py 가
echo   같이 보이는 자리에서 이 파일을 더블클릭하세요.
echo.
echo   이 폴더에 있는 것:
dir /b
goto END

REM ===========================================================================
:NOPYTHON
echo   [문제] 파이썬을 찾지 못했습니다.
echo.
echo   파이썬이 깔려 있어도, 깔 때 PATH 에 등록을 안 하면 이렇게 됩니다.
echo   아래를 그대로 사진 찍어 보내주시면 어디 있는지 찾아 드리겠습니다.
echo.
echo   ---------- 여기부터 사진 찍어 주세요 ----------
echo   [뒤져 본 자리]
if exist "%LOCALAPPDATA%\Programs\Python" (echo    있음 - %LOCALAPPDATA%\Programs\Python) else (echo    없음 - %LOCALAPPDATA%\Programs\Python)
if exist "%PROGRAMFILES%" dir /b "%PROGRAMFILES%" 2>nul | findstr /i "python anaconda conda"
if exist "C:\" dir /b "C:\" 2>nul | findstr /i "python anaconda conda"
if exist "%LOCALAPPDATA%\Programs" dir /b "%LOCALAPPDATA%\Programs" 2>nul | findstr /i "python anaconda conda"
echo.
echo   [이름으로 찾기]
where py 2>nul
where python 2>nul
where python3 2>nul
echo.
echo   [내 컴퓨터에서 python.exe 찾기 - 조금 걸립니다]
dir /s /b "%LOCALAPPDATA%\python.exe" 2>nul
dir /s /b "%USERPROFILE%\python.exe" 2>nul
echo   ---------- 여기까지 ----------
goto END

REM ===========================================================================
:NOLIB
echo.
echo   [문제] 부품(pycapcut)을 내려받지 못했습니다.
echo   회사 보안이 인터넷 내려받기를 막고 있을 수 있습니다.
echo.
echo   위에 나온 영어 메시지를 그대로 사진 찍어 보내주세요.
echo   개인 노트북에서 하시면 대부분 그냥 됩니다.
goto END

REM ===========================================================================
:END
echo.
echo   창을 닫으려면 아무 키나 누르세요.
pause >nul
