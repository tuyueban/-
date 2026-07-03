@echo off
setlocal

cd /d %~dp0\..

if exist .venv\Scripts\activate (
    call .venv\Scripts\activate
) else (
    echo [WARN] .venv not found, using current Python environment.
)

python scripts\run_daily_job.py --with-ai

endlocal