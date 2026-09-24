@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo.
echo ========================================
echo   cdp-debug installer
echo ========================================
echo.

set "SRC=%~dp0skills\cdp-observe"

REM ---- 1/3: pip install ----
echo [1/3] pip install -e .
python -m pip install -e "%SRC%\scripts"
echo       OK: cdp-mcp / cdp-proxy / cdp in PATH
echo.

REM ---- 2/3: register skill ----
echo [2/3] registering skill
set "SKILL_NAME=cdp-debug"

set "TRAE_SKILL_DIR=%USERPROFILE%\.trae-cn\skills\%SKILL_NAME%"
if exist "%USERPROFILE%\.trae-cn" (
    if not exist "%TRAE_SKILL_DIR%" mkdir "%TRAE_SKILL_DIR%"
    if not exist "%TRAE_SKILL_DIR%\scripts" mkdir "%TRAE_SKILL_DIR%\scripts"
    copy /Y "%SRC%\SKILL.md" "%TRAE_SKILL_DIR%\" >nul
    copy /Y "%SRC%\scripts\*.py" "%TRAE_SKILL_DIR%\scripts\" >nul
    copy /Y "%SRC%\scripts\pyproject.toml" "%TRAE_SKILL_DIR%\scripts\" >nul
    echo       TRAE skill: %TRAE_SKILL_DIR%
) else (
    echo       TRAE: skip [no .trae-cn dir]
)

set "CC_SKILL_DIR=%USERPROFILE%\.claude\skills\%SKILL_NAME%"
if exist "%USERPROFILE%\.claude" (
    if not exist "%CC_SKILL_DIR%" mkdir "%CC_SKILL_DIR%"
    if not exist "%CC_SKILL_DIR%\scripts" mkdir "%CC_SKILL_DIR%\scripts"
    copy /Y "%SRC%\SKILL.md" "%CC_SKILL_DIR%\" >nul
    copy /Y "%SRC%\scripts\*.py" "%CC_SKILL_DIR%\scripts\" >nul
    copy /Y "%SRC%\scripts\pyproject.toml" "%CC_SKILL_DIR%\scripts\" >nul
    echo       Claude Code skill: %CC_SKILL_DIR%
) else (
    echo       Claude Code: skip [no .claude dir]
)

echo.

REM ---- 3/3: MCP config ----
echo [3/3] MCP config

set "TRAE_MCP=%USERPROFILE%\.trae-cn\mcp.json"
if exist "%USERPROFILE%\.trae-cn" (
    python -c "import json,os,sys;p=sys.argv[1];d=json.load(open(p,encoding='utf-8')) if os.path.exists(p) else {};d.setdefault('mcpServers',{});d['mcpServers'].setdefault('cdp-debug',{'command':'cdp-mcp','args':[]});open(p,'w',encoding='utf-8').write(json.dumps(d,indent=2,ensure_ascii=False))" "%TRAE_MCP%"
    echo       TRAE MCP: %TRAE_MCP%
)

set "CC_MCP=%USERPROFILE%\.claude.json"
if exist "%USERPROFILE%\.claude" (
    python -c "import json,os,sys;p=sys.argv[1];d=json.load(open(p,encoding='utf-8')) if os.path.exists(p) else {};d.setdefault('mcpServers',{});d['mcpServers'].setdefault('cdp-debug',{'command':'cdp-mcp','args':[]});open(p,'w',encoding='utf-8').write(json.dumps(d,indent=2,ensure_ascii=False))" "%CC_MCP%"
    echo       Claude Code MCP: %CC_MCP%
)

echo.
echo ========================================
echo   Done. Restart IDE, then: cdp detect
echo ========================================
echo.
endlocal
