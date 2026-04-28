@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PYTHON_EXE=python"
set "CONFIG_PATH=%SCRIPT_DIR%configs\case_ingest.json"

pushd "%SCRIPT_DIR%"

%PYTHON_EXE% -m video_tagging_assistant.cli case-ingest --config "%CONFIG_PATH%"
set "EXIT_CODE=%ERRORLEVEL%"

popd
exit /b %EXIT_CODE%
