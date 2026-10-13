#!/usr/bin/env bash
# Дымовая проверка: запускает программу в виртуальном X-сервере и убеждается, что она
# открылась и работает, а не упала. Пример: tools/smoke.sh indicator-sticky-notes
# Своё окружение (XDG_*), поэтому заметки и настройки пользователя не затрагиваются.
set -u
[ $# -gt 0 ] || { echo "usage: $0 command [args...]" >&2; exit 2; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp"/run "$tmp"/data "$tmp"/config
chmod 700 "$tmp/run"
export XDG_RUNTIME_DIR="$tmp/run" XDG_DATA_HOME="$tmp/data" XDG_CONFIG_HOME="$tmp/config"

timeout "${SMOKE_SECONDS:-8}" xvfb-run -a "$@" >"$tmp/out" 2>&1
code=$?
grep -v "Deprecat\|^  " "$tmp/out" | tail -20

if [ "$code" -ne 124 ]; then
    echo "SMOKE FAILED: the program exited early with code $code" >&2
    exit 1
fi
if grep -q Traceback "$tmp/out"; then
    echo "SMOKE FAILED: Python traceback in the output" >&2
    exit 1
fi
notes="$tmp/data/indicator-sticky-notes/notes.json"
if [ ! -s "$notes" ]; then
    echo "SMOKE FAILED: the first note was not created ($notes)" >&2
    exit 1
fi
echo "SMOKE OK: the program started, created a note and kept running"
