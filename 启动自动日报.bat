@echo off
cd /d "%~dp0"
python daily_job_search_quick.py
python send_email.py
pause