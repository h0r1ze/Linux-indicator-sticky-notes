#!/usr/bin/env bash
# Пересобирает скриншоты: docs/images/*.png (русский) и docs/images/en/*.png (английский).
# Нужны: xvfb-run, dbus-run-session, marco (любой оконный менеджер подойдёт),
# ImageMagick (import, convert) и pycairo. Один язык: ./tools/make_screenshots.sh en
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
export PYTHONPATH="$PWD"

for lang in ${@:-ru en}; do
    export SHOT_LANG="$lang"
    # Заметки и палитра: настоящие виджеты в буфере, масштаб 2 для чёткости.
    GDK_SCALE=2 xvfb-run -a -s "-screen 0 1280x800x24+32" python3 tools/make_screenshots.py scenes

    # Менеджер, настройки, меню: настоящие окна под оконным менеджером.
    for which in manager settings tray note-menu font-menu help; do
        xvfb-run -a -s "-screen 0 900x900x24" dbus-run-session -- \
            sh -c "marco --replace --no-composite >/dev/null 2>&1 & sleep 3; python3 tools/make_screenshots.py windows $which"
    done
done
ls -la docs/images docs/images/en 2>/dev/null || true
