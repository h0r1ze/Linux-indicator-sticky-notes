#!/usr/bin/env bash
# Собирает .deb (Debian, Ubuntu, Linux Mint): ./packaging/build-deb.sh
# Нужен dpkg-deb. STAGE_ONLY=1 — только подготовить дерево пакета.
set -euo pipefail

root="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$root"
version="$(python3 -c 'import indicator_sticky_notes as m; print(m.__version__)')"
stage="$root/build/deb/indicator-sticky-notes_${version}"

rm -rf "$stage"

# Файлы раскладываем сами, без setuptools: его раскладка зависит от дистрибутива сборки
# (на Ubuntu setup.py install кладёт всё в /usr/local, и пакет не работает на других версиях).
dist="$stage/usr/lib/python3/dist-packages"
install -d "$dist" "$stage/usr/bin" "$stage/usr/share/applications" \
    "$stage/usr/share/icons/hicolor/scalable/apps" "$stage/usr/share/doc/indicator-sticky-notes"
cp -r "$root/indicator_sticky_notes" "$dist/"
rm -rf "$dist/indicator_sticky_notes/__pycache__"
install -m 755 "$root/bin/indicator-sticky-notes" "$stage/usr/bin/indicator-sticky-notes"
sed -i '1s|.*|#!/usr/bin/python3|' "$stage/usr/bin/indicator-sticky-notes"
install -m 644 "$root/data/indicator-sticky-notes.desktop" "$stage/usr/share/applications/"
install -m 644 "$root/data/icons/hicolor/scalable/apps/indicator-sticky-notes.svg" \
    "$stage/usr/share/icons/hicolor/scalable/apps/"
install -m 644 "$root/LICENSE" "$stage/usr/share/doc/indicator-sticky-notes/copyright"
install -m 644 "$root/README.md" "$stage/usr/share/doc/indicator-sticky-notes/README.md"
chmod -R u=rwX,go=rX "$stage"

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
