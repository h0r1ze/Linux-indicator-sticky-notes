#!/usr/bin/env bash
# Собирает пакет для Arch Linux и производных (Manjaro, EndeavourOS): ./packaging/build-arch.sh
# Нужны: base-devel, python-build, python-installer, python-setuptools, python-wheel, git.
# Собирается текущее состояние git-дерева; makepkg нельзя запускать от root.
set -euo pipefail

root="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$root"

command -v makepkg >/dev/null || { echo "Не найден makepkg: это не Arch Linux?" >&2; exit 1; }

version="$(python3 -c 'import indicator_sticky_notes as m; print(m.__version__)')"
work="$root/build/arch"
rm -rf "$work"
mkdir -p "$work"

# Исходники берём из локального git (а не с GitHub), поэтому в PKGBUILD подменяем source.
git ls-files -z | tar --null -T - \
    --transform "s,^,Linux-indicator-sticky-notes-${version}/," \
    -czf "$work/indicator-sticky-notes-${version}.tar.gz"
sed -e 's|^source=.*|source=("$pkgname-$pkgver.tar.gz")|' packaging/arch/PKGBUILD > "$work/PKGBUILD"

cd "$work"
makepkg -f --cleanbuild ${MAKEPKG_FLAGS:-}
cp -v ./*.pkg.tar.* "$root/build/"
