#!/usr/bin/env bash
# Starts HandPilot. Extra arguments are passed on (e.g. --dry-run, --debug).
cd "$(dirname "$0")/.."
exec .venv-app/bin/python HandPilot.pyw "$@"
