#!/usr/bin/env bash
# Универсальный установщик для любого Linux (Debian, Ubuntu, Mint, Fedora, RHEL и клоны, RED OS,
# Arch, openSUSE, Alpine, Void...) / Universal installer for any Linux distribution.
#
#   ./install.sh                  установить для себя в ~/.local (root не нужен; от root: /usr/local)
#   ./install.sh --prefix /usr    установить в другое место
#   ./install.sh --no-deps        не ставить системные пакеты (GTK3, PyGObject)
#   ./install.sh --uninstall      удалить программу (заметки и настройки остаются)
#
# Программа — чистый Python: ставятся только библиотеки GTK 3 и PyGObject из пакетов дистрибутива.
set -euo pipefail

root="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
app="indicator-sticky-notes"
module="indicator_sticky_notes"

ru=0
case "${LC_ALL:-${LC_MESSAGES:-${LANGUAGE:-${LANG:-}}}}" in ru*) ru=1 ;; esac
say() { if [ "$ru" = 1 ]; then printf '%s\n' "$2"; else printf '%s\n' "$1"; fi; }
die() { say "Error: $1" "Ошибка: $2" >&2; exit 1; }

prefix=""
deps=1
uninstall=0
while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) [ $# -ge 2 ] || die "--prefix needs a directory" "--prefix требует папку"; prefix="$2"; shift ;;
        --prefix=*) prefix="${1#--prefix=}" ;;
        --no-deps) deps=0 ;;
        --uninstall) uninstall=1 ;;
        -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
        *) die "unknown option: $1" "неизвестный параметр: $1" ;;
    esac
    shift
done
if [ -z "$prefix" ]; then
    if [ "$(id -u)" = 0 ]; then prefix=/usr/local; else prefix="$HOME/.local"; fi
fi

bin="$prefix/bin"
lib="$prefix/share/$app/lib"
apps="$prefix/share/applications"
icons="$prefix/share/icons/hicolor/scalable/apps"

if [ "$uninstall" = 1 ]; then
    rm -rf "$prefix/share/$app"
    rm -f "$bin/$app" "$apps/$app.desktop" "$icons/$app.svg"
    say "Removed from $prefix. Your notes and settings were left in place." \
        "Удалено из $prefix. Заметки и настройки не тронуты."
    exit 0
fi

have_gtk() {
    python3 -c "import gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk" 2>/dev/null
}

as_root() {
    if [ "$(id -u)" = 0 ]; then "$@"
    elif command -v sudo >/dev/null 2>&1; then sudo "$@"
    else die "root rights are needed to install packages (install sudo or run as root)" \
             "для установки пакетов нужны права root (поставьте sudo или запустите от root)"
    fi
}

install_deps() {
    if command -v python3 >/dev/null 2>&1 && have_gtk; then
        say "GTK 3 and PyGObject are already installed." "GTK 3 и PyGObject уже установлены."
        return
    fi
    say "Installing system packages (GTK 3, PyGObject)..." "Ставлю системные пакеты (GTK 3, PyGObject)..."
    if command -v apt-get >/dev/null 2>&1; then
        as_root apt-get update
        as_root apt-get install -y python3 python3-gi gir1.2-gtk-3.0
    elif command -v dnf >/dev/null 2>&1; then
        as_root dnf install -y python3 python3-gobject gtk3 libX11
    elif command -v yum >/dev/null 2>&1; then
        as_root yum install -y python3 python3-gobject gtk3 libX11
    elif command -v pacman >/dev/null 2>&1; then
        as_root pacman -S --needed --noconfirm python python-gobject gtk3 libx11
    elif command -v zypper >/dev/null 2>&1; then
        as_root zypper --non-interactive install python3 python3-gobject python3-gobject-Gdk typelib-1_0-Gtk-3_0 libX11-6
    elif command -v apk >/dev/null 2>&1; then
        as_root apk add python3 py3-gobject3 gtk+3.0
    elif command -v xbps-install >/dev/null 2>&1; then
        as_root xbps-install -Sy python3 python3-gobject gtk+3
    else
        die "no known package manager. Install Python 3.9+, PyGObject and GTK 3 yourself, then run with --no-deps" \
            "не найден известный менеджер пакетов. Поставьте Python 3.9+, PyGObject и GTK 3 сами и запустите с --no-deps"
    fi
}

if [ "$deps" = 1 ]; then
    install_deps
fi
command -v python3 >/dev/null 2>&1 || die "python3 not found" "не найден python3"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' \
    || die "Python 3.9 or newer is required" "нужен Python 3.9 или новее"
have_gtk || die "Python cannot import GTK 3 (package python3-gi / python3-gobject, gtk3). Run without --no-deps." \
                "Python не видит GTK 3 (пакеты python3-gi / python3-gobject, gtk3). Запустите без --no-deps."

# Файлы программы.
rm -rf "$lib"
mkdir -p "$lib" "$bin" "$apps" "$icons"
cp -r "$root/$module" "$lib/"
find "$lib" -name __pycache__ -type d -prune -exec rm -rf {} +
install -m 644 "$root/data/icons/hicolor/scalable/apps/$app.svg" "$icons/$app.svg"

# Команда запуска: не зависит от того, где лежит папка с исходниками.
cat > "$bin/$app" <<LAUNCHER
#!/bin/sh
PYTHONPATH="$lib\${PYTHONPATH:+:\$PYTHONPATH}" exec python3 -m $module "\$@"
LAUNCHER
chmod 755 "$bin/$app"

# Ярлык в меню приложений (Exec — полный путь: ~/.local/bin может не быть в PATH сеанса).
sed "s|^Exec=.*|Exec=$bin/$app|" "$root/data/$app.desktop" > "$apps/$app.desktop"
chmod 644 "$apps/$app.desktop"

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$apps" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t -f "$prefix/share/icons/hicolor" 2>/dev/null || true

say "Installed to $prefix. Run: $app (or find \"Sticky Notes\" in the applications menu)." \
    "Установлено в $prefix. Запуск: $app (или «Стикеры» в меню приложений)."
case ":$PATH:" in
    *":$bin:"*) ;;
    *) say "Note: $bin is not in your PATH; use the menu entry or the full path $bin/$app." \
           "Папки $bin нет в PATH: запускайте из меню приложений или по полному пути $bin/$app." ;;
esac
say "Uninstall: ./install.sh --uninstall" "Удаление: ./install.sh --uninstall"
