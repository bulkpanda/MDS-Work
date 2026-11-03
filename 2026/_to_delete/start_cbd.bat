@echo off
cd /d "%~dp0"
start cmd /k "python cbd_gradio.py"
timeout /t 3 /nobreak
ngrok http --domain=coerce-octane-gilled.ngrok-free.dev 7861
