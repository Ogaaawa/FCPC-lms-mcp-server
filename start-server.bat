@echo off
chcp 65001 >nul
rem Publish the MCP server with a temporary Cloudflare quick tunnel.
rem Double-click, or run from a command prompt. Closing the window stops it.
rem
rem For a host that must survive a reboot, do NOT use this. Install a named
rem tunnel and a scheduled task instead - see deploy\windows.md.
setlocal
cd /d "%~dp0"

if not defined PORT set "PORT=8000"

if not exist "venv\Scripts\python.exe" goto no_venv
where cloudflared >nul 2>&1
if errorlevel 1 goto no_cloudflared

set "LOG=%TEMP%\moodle-tunnel.log"
if exist "%LOG%" del "%LOG%" >nul 2>&1

echo Requesting a public address...
start "moodle-tunnel" /b cmd /c "cloudflared tunnel --url http://127.0.0.1:%PORT% --no-autoupdate > "%LOG%" 2>&1"

rem Flat loop on purpose: variables set inside a parenthesised block are not
rem visible to the next line without delayed expansion, which is easy to get
rem wrong here.
set "PUBLIC="
set /a TRIES=0

:wait_loop
set /a TRIES+=1
if %TRIES% gtr 30 goto no_address
timeout /t 2 /nobreak >nul
for /f "usebackq delims=" %%u in (`powershell -NoProfile -Command "try{(Select-String -Path '%LOG%' -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -AllMatches).Matches[0].Value}catch{''}"`) do set "PUBLIC=%%u"
if not defined PUBLIC goto wait_loop

echo Starting the MCP server...
echo.
echo ============================================================
echo  Give this URL to your students (the same one for everyone)
echo.
echo    %PUBLIC%/mcp
echo.
echo  They paste it into Claude under
echo  Settings ^> Connectors ^> Add custom connector.
echo ============================================================
echo.
echo This address disappears when this window closes, and a new one is
echo issued next time. Press Ctrl+C to quit.
echo.

rem The public address becomes the OAuth issuer, so it has to be passed in.
"venv\Scripts\python.exe" remote_server.py --port %PORT% --public-url %PUBLIC%

goto cleanup

:no_venv
echo.
echo The virtual environment is missing. Run setup.bat first.
echo.
pause
exit /b 1

:no_cloudflared
echo.
echo cloudflared was not found.
echo Download it from
echo   https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
echo and make sure it is on your PATH.
echo.
pause
exit /b 1

:no_address
echo.
echo Could not get a public address after 60 seconds.
echo Check the network connection, then look at:
echo   %LOG%
echo.
call :cleanup_tunnel
pause
exit /b 1

:cleanup
call :cleanup_tunnel
exit /b 0

:cleanup_tunnel
rem This stops every cloudflared process, not just the one started above.
rem Do not run this script on a machine that also serves a named tunnel.
taskkill /f /im cloudflared.exe >nul 2>&1
exit /b 0
