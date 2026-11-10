#!/bin/sh
# Uppcoder Spark looks for this at the repository root.
cd "$(dirname "$0")/web"
exec python -m uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
