@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%"

python -m video_tagging_assistant.cli case-ingest --config "%SCRIPT_DIR%configs\case_ingest.json"
set "EXIT_CODE=%ERRORLEVEL%"

popd
exit /b %EXIT_CODE%
