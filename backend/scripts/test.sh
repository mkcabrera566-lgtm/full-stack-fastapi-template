#!/usr/bin/env bash

set -e
set -x

python scripts/test_backend.py --title "${@-coverage}"
