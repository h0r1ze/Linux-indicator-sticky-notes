import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from indicator_sticky_notes import legacy


class LegacyMigrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.data, self.config = self.tmp / "data", self.tmp / "config"
        env = {"XDG_DATA_HOME": str(self.data), "XDG_CONFIG_HOME": str(self.config)}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_moves_notes_and_settings(self):
        (self.data / legacy.OLD).mkdir(parents=True)
        (self.data / legacy.OLD / "notes.json").write_text("{}")
        (self.config / legacy.OLD).mkdir(parents=True)
        (self.config / legacy.OLD / "settings.json").write_text("{}")
        legacy.migrate()
        self.assertTrue((self.data / legacy.NEW / "notes.json").exists())
        self.assertTrue((self.config / legacy.NEW / "settings.json").exists())
        self.assertFalse((self.data / legacy.OLD).exists())
        legacy.migrate()  # повторный запуск ничего не ломает
        self.assertTrue((self.data / legacy.NEW / "notes.json").exists())

    def test_does_not_overwrite_new_data(self):
        for root, text in ((legacy.OLD, "old"), (legacy.NEW, "new")):
            (self.data / root).mkdir(parents=True)
            (self.data / root / "notes.json").write_text(text)
        legacy.migrate()
        self.assertEqual((self.data / legacy.NEW / "notes.json").read_text(), "new")
        self.assertEqual((self.data / legacy.OLD / "notes.json").read_text(), "old")

    def test_rewrites_autostart_entry(self):
        folder = self.config / "autostart"
        folder.mkdir(parents=True)
        (folder / f"{legacy.OLD}.desktop").write_text(
            "[Desktop Entry]\nExec=/usr/bin/indicat-sticky-notes\nIcon=indicat-sticky-notes\n"
            "Path=/x\n")
        legacy.migrate()
        self.assertFalse((folder / f"{legacy.OLD}.desktop").exists())
        text = (folder / f"{legacy.NEW}.desktop").read_text()
        self.assertIn("Exec=/usr/bin/indicator-sticky-notes", text)
        self.assertNotIn("indicat-", text.replace("indicator-", ""))

    def test_nothing_to_migrate(self):
        legacy.migrate()
        self.assertFalse(self.data.exists())


if __name__ == "__main__":
    unittest.main()
