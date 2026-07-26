#!/bin/bash
# OpenMemo startup script
cd "$(dirname "$0")"
source .venv/bin/activate
python -m openmemo.server
