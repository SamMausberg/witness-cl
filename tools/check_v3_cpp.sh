#!/usr/bin/env bash
set -euo pipefail
mkdir -p artifacts/v3
bin=$(mktemp)
trap 'rm -f "$bin"' EXIT
c++ -std=c++17 -O2 -Wall -Wextra -fsanitize=undefined kernels/continuation_cpu_test.cpp -o "$bin"
"$bin"
