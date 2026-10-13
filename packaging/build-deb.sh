#!/usr/bin/env bash
# Собирает .deb (Debian, Ubuntu, Linux Mint): ./packaging/build-deb.sh
# Нужны python3-setuptools и dpkg-deb. STAGE_ONLY=1 — только подготовить дерево пакета.
set -euo pipefail

root="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$root"
version="$(python3 -c 'import indicator_sticky_notes as m; print(m.__version__)')"
stage="$root/build/deb/indicator-sticky-notes_${version}"

rm -rf "$stage"
mkdir -p "$stage"
python3 setup.py -q install --root="$stage" --prefix=/usr --single-version-externally-managed --record=/dev/null

# setuptools кладёт модули в site-packages, а Debian ждёт dist-packages.
dist="$stage/usr/lib/python3/dist-packages"
mkdir -p "$dist"
for sp in "$stage"/usr/lib/python3*/site-packages; do
    [ -d "$sp" ] && cp -a "$sp"/. "$dist"/ && rm -rf "$sp"
done
find "$stage" -name __pycache__ -type d -prune -exec rm -rf {} +

mkdir -p "$stage/DEBIAN"
cat > "$stage/DEBIAN/control" <<CONTROL
Package: indicator-sticky-notes
Version: ${version}
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.9), python3-gi, gir1.2-gtk-3.0
Replaces: indicat-sticky-notes (<< 0.2.3)
Conflicts: indicat-sticky-notes (<< 0.2.3)
Maintainer: h0r1ze <87946256+h0r1ze@users.noreply.github.com>
Homepage: https://github.com/h0r1ze/Linux-indicator-sticky-notes
Description: Sticky notes for the Linux desktop (GTK3)
 Coloured notes with a designer palette, checklists, formatting, groups, trash,
 search, backups, sync through a shared folder, global hotkeys and a tray icon.
CONTROL

if [ "${STAGE_ONLY:-0}" = "1" ]; then
    echo "Дерево пакета: $stage"
    exit 0
fi
dpkg-deb --build --root-owner-group "$stage" "$root/build/indicator-sticky-notes_${version}_all.deb"
echo "Готово: build/indicator-sticky-notes_${version}_all.deb"
