@echo off
cd /d "c:\Users\balup\OneDrive\Desktop\finalproject\TradingAgents-main"
echo [%date% %time%] Starting daily screener run... >> daily_run.log
python run_daily.py --limit 40 >> daily_run.log 2>&1
echo [%date% %time%] Daily screener run complete. >> daily_run.log
