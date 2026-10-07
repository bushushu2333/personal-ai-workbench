#!/bin/zsh
set -e
APP_DIR="${0:A:h}"
cd "$APP_DIR"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv --system-site-packages .venv
fi
if ! .venv/bin/python -c 'import fastapi, uvicorn, yaml, psutil' >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements.txt
fi
.venv/bin/python service.py start
open 'http://127.0.0.1:4186'
