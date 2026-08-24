@echo off
chcp 65001 >nul
rem Setup launcher for Windows. Double-click to open the setup window.
rem It creates the virtual environment and installs libraries on first run.
cd /d "%~dp0"

echo Moodle アシスタントのセットアップを準備しています...

rem --- Python を探す（py ランチャー優先、無ければ python） ---
set "PY="
where py >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    where python >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if not defined PY goto no_python

rem --- 仮想環境 ---
if exist "venv\Scripts\python.exe" goto venv_ok
echo 初回準備中です。数分かかることがあります...
%PY% -m venv venv
if errorlevel 1 goto venv_failed
:venv_ok
set "VENV_PY=%CD%\venv\Scripts\python.exe"

rem --- ライブラリ（入れ直したいときは venv フォルダごと削除する） ---
if exist "venv\.requirements-stamp" goto deps_ok
echo 必要なライブラリをインストールしています...
"%VENV_PY%" -m pip install -q --upgrade pip
"%VENV_PY%" -m pip install -q -r requirements.txt
if errorlevel 1 goto deps_failed
echo done> "venv\.requirements-stamp"
:deps_ok

rem --- Gemini CLI（無ければ入れる。失敗してもセットアップは続行する） ---
where gemini >nul 2>&1
if not errorlevel 1 goto gemini_ok
where npm >nul 2>&1
if errorlevel 1 goto no_node
echo Gemini CLI をインストールしています...
call npm install -g @google/gemini-cli >nul 2>&1
if errorlevel 1 echo   -^> 失敗しました。あとで手動で: npm install -g @google/gemini-cli
goto gemini_ok
:no_node
echo Node.js が見つからないため Gemini CLI は入れられません。
echo   Gemini から使う場合は https://nodejs.org/ から Node.js を入れてください。
:gemini_ok

echo セットアップ画面を開きます。
"%VENV_PY%" setup_gui.py
echo.
pause
exit /b 0

:no_python
echo.
echo Python が見つかりません。
echo https://www.python.org/downloads/ から Python をインストールしてください。
echo インストール時に「Add Python to PATH」に必ずチェックを入れてください。
echo.
pause
exit /b 1

:venv_failed
echo 仮想環境の作成に失敗しました。
pause
exit /b 1

:deps_failed
echo インストールに失敗しました。
pause
exit /b 1
