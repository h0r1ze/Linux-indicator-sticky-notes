"""Упаковка: версии во всех пакетах совпадают, скрипты и ярлыки корректны."""
import importlib.util
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from indicator_sticky_notes import __version__

ROOT = Path(__file__).resolve().parent.parent


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


class PackagingTest(unittest.TestCase):
    def test_versions_match(self):
        spec = re.search(r"^Version:\s*(\S+)", read("packaging/rpm/indicator-sticky-notes.spec"), re.M)
        pkgbuild = re.search(r"^pkgver=(\S+)", read("packaging/arch/PKGBUILD"), re.M)
        self.assertEqual(spec.group(1), __version__)
        self.assertEqual(pkgbuild.group(1), __version__)

    def test_spec_changelog_mentions_current_version(self):
        self.assertIn(f"- {__version__}-", read("packaging/rpm/indicator-sticky-notes.spec"))

    def test_no_leftover_old_name(self):
        """Опечатка «indicat» допустима только там, где говорится о старом пакете."""
        allowed = ("legacy.py", "test_legacy.py", "test_packaging.py", ".spec", "PKGBUILD",
                   "build-deb.sh", "README.md", "README.en.md", "ci.yml", "install.sh")
        offenders = []
        files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split("\n")
        for name in files:
            path = ROOT / name
            if not name or path.suffix in (".png", ".svg") or name.endswith(allowed):
                continue
            if re.search(r"indicat(?!or)", path.read_text(encoding="utf-8", errors="ignore")):
                offenders.append(name)
        self.assertEqual(offenders, [])

    def test_shell_scripts_have_valid_syntax(self):
        for script in ("install.sh", "run.sh", "create-shortcut.sh", "packaging/build-deb.sh",
                       "packaging/build-rpm.sh", "packaging/build-arch.sh", "tools/smoke.sh",
                       "tools/make_screenshots.sh"):
            result = subprocess.run(["bash", "-n", str(ROOT / script)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f"{script}: {result.stderr}")

    @unittest.skipUnless(shutil.which("desktop-file-validate"), "нет desktop-file-validate")
    def test_desktop_file_is_valid(self):
        result = subprocess.run(["desktop-file-validate", str(ROOT / "data/indicator-sticky-notes.desktop")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(importlib.util.find_spec("setuptools"), "нет setuptools")
    def test_metadata_lives_in_setup_py_for_old_setuptools(self):
        """Старые setuptools (RHEL 9 и клоны) не читают [project] из pyproject.toml."""
        self.assertNotIn("[project]", read("pyproject.toml"))
        result = subprocess.run(["python3", "setup.py", "--name", "--version"], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(result.stdout.split(), ["indicator-sticky-notes", __version__])

    def test_launcher_script_is_plain_and_executable(self):
        launcher = ROOT / "bin" / "indicator-sticky-notes"
        self.assertTrue(launcher.stat().st_mode & 0o111, "у команды запуска нет права на исполнение")
        text = launcher.read_text(encoding="utf-8")
        self.assertIn("from indicator_sticky_notes.__main__ import main", text)
        self.assertNotIn("pkg_resources", text)  # без поиска метаданных пакета

    def test_deb_tree_has_files_where_debian_expects_them(self):
        """Дерево .deb: модуль в dist-packages, ничего в /usr/local, команда с системным python."""
        env = {**os.environ, "STAGE_ONLY": "1"}
        run = subprocess.run(["bash", str(ROOT / "packaging/build-deb.sh")], capture_output=True,
                             text=True, env=env)
        self.assertEqual(run.returncode, 0, run.stderr)
        stage = ROOT / "build/deb" / f"indicator-sticky-notes_{__version__}"
        self.assertTrue((stage / "usr/lib/python3/dist-packages/indicator_sticky_notes/app.py").exists())
        self.assertFalse((stage / "usr/local").exists())
        launcher = stage / "usr/bin/indicator-sticky-notes"
        self.assertEqual(launcher.read_text(encoding="utf-8").split("\n")[0], "#!/usr/bin/python3")
        self.assertTrue(launcher.stat().st_mode & 0o111)
        self.assertTrue((stage / "usr/share/applications/indicator-sticky-notes.desktop").exists())
        self.assertTrue((stage / "usr/share/doc/indicator-sticky-notes/copyright").exists())
        control = (stage / "DEBIAN/control").read_text(encoding="utf-8")
        self.assertIn(f"Version: {__version__}", control)
        self.assertIn("Replaces: indicat-sticky-notes", control)

    def test_installer_lists_package_managers_of_major_distributions(self):
        text = read("install.sh")
        for manager in ("apt-get", "dnf", "yum", "pacman", "zypper", "apk", "xbps-install"):
            self.assertIn(manager, text)

    def test_installer_installs_into_a_prefix_and_uninstalls(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp) / "prefix"
            run = subprocess.run(["bash", str(ROOT / "install.sh"), "--prefix", str(prefix), "--no-deps"],
                                 capture_output=True, text=True)
            if "cannot import GTK" in run.stderr or "не видит GTK" in run.stderr:
                self.skipTest("нет GTK 3 для Python")
            self.assertEqual(run.returncode, 0, run.stderr)
            launcher = prefix / "bin" / "indicator-sticky-notes"
            self.assertTrue(launcher.exists())
            self.assertTrue((prefix / "share/indicator-sticky-notes/lib/indicator_sticky_notes/app.py").exists())
            desktop = (prefix / "share/applications/indicator-sticky-notes.desktop").read_text(encoding="utf-8")
            self.assertIn(f"Exec={launcher}\n", desktop)
            self.assertTrue((prefix / "share/icons/hicolor/scalable/apps/indicator-sticky-notes.svg").exists())
            subprocess.run(["bash", str(ROOT / "install.sh"), "--prefix", str(prefix), "--uninstall"],
                           capture_output=True, check=True)
            self.assertFalse(launcher.exists())
            self.assertFalse((prefix / "share/indicator-sticky-notes").exists())


if __name__ == "__main__":
    unittest.main()
