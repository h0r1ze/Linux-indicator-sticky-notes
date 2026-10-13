"""Перевод интерфейса: каталог, выбор языка, английский режим и переключение с перезапуском."""
import ast
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from indicator_sticky_notes import i18n
from indicator_sticky_notes.i18n import _
from indicator_sticky_notes.translations_en import EN

PACKAGE = Path(__file__).resolve().parent.parent / "indicator_sticky_notes"
CYRILLIC = re.compile("[А-Яа-яЁё]")

try:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
    HAVE_DISPLAY = Gtk.init_check()[0]
except (ImportError, ValueError):
    HAVE_DISPLAY = False

if HAVE_DISPLAY:
    from indicator_sticky_notes.app import StickyApp
    from indicator_sticky_notes.settings import Settings
    from indicator_sticky_notes.storage import NoteStore


def marked_strings():
    """Все литералы, помеченные как _("…") и N_("…") в коде пакета."""
    found = {}
    for path in sorted(PACKAGE.glob("*.py")):
        if path.name in ("i18n.py", "translations_en.py"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in ("_", "N_") and node.args
                    and isinstance(node.args[0], ast.Constant)):
                found.setdefault(node.args[0].value, f"{path.name}:{node.lineno}")
    return found


class CatalogTest(unittest.TestCase):
    def test_every_marked_string_has_english(self):
        missing = {s: where for s, where in marked_strings().items() if s not in EN}
        self.assertEqual(missing, {})

    def test_catalog_has_no_unused_entries(self):
        unused = [s for s in EN if s not in marked_strings()]
        self.assertEqual(unused, [])

    def test_translations_are_not_russian(self):
        for ru, en in EN.items():
            self.assertFalse(CYRILLIC.search(en), f"в английском тексте остался русский: {en!r}")

    def test_placeholders_match(self):
        field = re.compile(r"\{\w*\}")
        for ru, en in EN.items():
            self.assertEqual(sorted(field.findall(ru)), sorted(field.findall(en)), ru)

    def test_user_text_in_code_is_always_marked(self):
        """Русский литерал вне _() допустим только в docstring и в известных исключениях."""
        # внутренние сообщения об ошибках и двуязычные подписи переключателя языка
        allowed = {"не цвет #rrggbb", "нет таких настроек", "Язык: Русский", "Язык / Language"}
        offenders = []
        for path in sorted(PACKAGE.glob("*.py")):
            if path.name in ("i18n.py", "translations_en.py"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Constant) and isinstance(node.value, str)
                        and CYRILLIC.search(node.value)):
                    continue
                parent = parents[node]
                if isinstance(parent, ast.Expr):  # docstring
                    continue
                call = parent
                while call is not None and not (isinstance(call, ast.Call)
                                                and isinstance(call.func, ast.Name)
                                                and call.func.id in ("_", "N_")):
                    call = parents.get(call)
                if call is None and not any(a in node.value for a in allowed):
                    offenders.append(f"{path.name}:{node.lineno}: {node.value[:50]!r}")
        self.assertEqual(offenders, [])


class LanguageChoiceTest(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("ru")

    def env(self, **values):
        clean = {k: "" for k in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG")}
        return mock.patch.dict(os.environ, {**clean, **values})

    def test_explicit_choice_wins(self):
        with self.env(LC_ALL="ru_RU.UTF-8"):
            self.assertEqual(i18n.set_language("en"), "en")
            self.assertEqual(i18n.set_language("ru"), "ru")

    def test_system_language_from_environment(self):
        with self.env(LANG="ru_RU.UTF-8"):
            self.assertEqual(i18n.system_language(), "ru")
        with self.env(LANG="de_DE.UTF-8"):
            self.assertEqual(i18n.system_language(), "en")
        with self.env(LC_ALL="ru_RU.UTF-8", LANG="en_US.UTF-8"):
            self.assertEqual(i18n.system_language(), "ru")  # LC_ALL главнее LANG
        with self.env(LANGUAGE="ru:en"):
            self.assertEqual(i18n.system_language(), "ru")
        with self.env(LANG="C"):
            self.assertEqual(i18n.system_language(), "en")
        with self.env():
            self.assertEqual(i18n.system_language(), "en")

    def test_translate(self):
        i18n.set_language("en")
        self.assertEqual(_("Выход"), "Quit")
        self.assertEqual(_("нет такой строки"), "нет такой строки")  # без перевода — как есть
        i18n.set_language("ru")
        self.assertEqual(_("Выход"), "Выход")

    def test_plural_forms(self):
        ru = ("заметка", "заметки", "заметок")
        en = ("note", "notes")
        i18n.set_language("ru")
        got = [i18n.plural(n, ru, en) for n in (1, 2, 5, 11, 12, 21, 22, 25, 111, 0)]
        self.assertEqual(got, [ru[0], ru[1], ru[2], ru[2], ru[2], ru[0], ru[1], ru[2], ru[2], ru[2]])
        i18n.set_language("en")
        self.assertEqual([i18n.plural(n, ru, en) for n in (1, 2, 0)], ["note", "notes", "notes"])


@unittest.skipUnless(HAVE_DISPLAY, "нет дисплея")
class EnglishInterfaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.settings = Settings(root / "settings.json")
        self.settings.update(language="en")
        self.store = NoteStore(root / "notes.json")
        self.store.add(title="Shopping", text="milk", color="yellow")
        self.app = StickyApp(self.store, root / "backups", settings=self.settings, use_hotkeys=False)
        self.app._message = lambda *a, **k: None
        self.app.setup()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for window in list(self.app.windows.values()):
            window.destroy()
        for extra in (self.app.manager, self.app.settings_window, self.app.help_window):
            if extra:
                extra.destroy()
        self.app.shutdown_services()
        i18n.set_language("ru")
        self.tmp.cleanup()

    def labels(self, menu):
        result = []
        for item in menu.get_children():
            if isinstance(item, Gtk.MenuItem) and item.get_label():
                result.append(item.get_label())
                if item.get_submenu():
                    result.extend(self.labels(item.get_submenu()))
        return result

    def widget_texts(self, widget):
        texts = []
        if isinstance(widget, (Gtk.Label, Gtk.Button)):
            texts.append(widget.get_label() or "")
        if isinstance(widget, Gtk.Widget):
            texts.append(widget.get_tooltip_text() or "")
        if isinstance(widget, Gtk.Container):
            for child in widget.get_children():
                texts.extend(self.widget_texts(child))
        return texts

    def assert_english(self, texts, where):
        russian = [t for t in texts if CYRILLIC.search(t)]
        self.assertEqual(russian, [], f"русский текст в английском интерфейсе: {where}")

    def test_current_language_is_english(self):
        self.assertEqual(i18n.current(), "en")

    def test_tray_menu(self):
        menu = self.app.build_tray_menu()
        labels = self.labels(menu)
        self.assertIn("New note", labels)
        self.assertIn("Quit", labels)
        self.assertIn("Язык: Русский", labels)  # пункт переключения написан на языке, на который переключает
        self.assert_english([t for t in labels if t != "Язык: Русский"], "меню трея")

    def test_note_window_and_menu(self):
        window = list(self.app.windows.values())[0]
        self.assert_english(self.widget_texts(window), "окно заметки")
        menu = window.build_menu()
        labels = [t for t in self.labels(menu) if t != "Язык: Русский"]
        self.assert_english(labels, "меню заметки")
        self.assertIn("Font size", labels)
        self.assertIn("Sticky Notes", labels)

    def test_settings_manager_help(self):
        self.app.open_settings()
        texts = self.widget_texts(self.app.settings_window)
        self.assert_english([t for t in texts if t != "Язык / Language"], "настройки")
        self.assertEqual(self.app.settings_window.get_title(), "Settings")
        self.app.open_manager()
        self.assert_english(self.widget_texts(self.app.manager), "менеджер")
        self.assertEqual(self.app.manager.get_title(), "Notes")
        self.app.open_help()
        buffer = self.app.help_window.view.get_buffer()
        self.assert_english([buffer.get_text(*buffer.get_bounds(), True)], "справка")

    def test_about_dialog(self):
        from indicator_sticky_notes import help_window

        dialog = help_window.build_about_dialog()
        self.assertEqual(dialog.get_program_name(), "Sticky Notes")
        self.assert_english([dialog.get_comments()], "О программе")
        dialog.destroy()

    def test_trash_texts(self):
        self.app.open_manager()
        manager = self.app.manager
        note = self.store.notes[0]
        self.app.delete_note(note.id)
        manager.refresh()
        self.assertEqual(manager.status.get_text(), "Notes: 0")
        self.assertIn("Trash (1)", manager.stack.child_get_property(manager.trash_page, "title"))

    def test_desktop_entry_uses_language(self):
        from indicator_sticky_notes import autostart

        self.assertIn("Name=Sticky Notes\n", autostart.desktop_entry())
        self.assertEqual(autostart.shortcut_name(), "Sticky Notes.desktop")


@unittest.skipUnless(HAVE_DISPLAY, "нет дисплея")
class LanguageSwitchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.settings = Settings(root / "settings.json")
        self.store = NoteStore(root / "notes.json")
        self.app = StickyApp(self.store, root / "backups", settings=self.settings, use_hotkeys=False)
        self.app.setup()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for window in list(self.app.windows.values()):
            window.destroy()
        for extra in (self.app.manager, self.app.settings_window):
            if extra:
                extra.destroy()
        self.app.shutdown_services()
        i18n.set_language("ru")
        self.tmp.cleanup()

    def test_default_is_system_and_follows_environment(self):
        self.assertEqual(self.settings["language"], "system")
        self.assertEqual(i18n.current(), "ru")  # тесты запускаются с LC_ALL=ru_RU

    def test_changing_language_saves_and_requests_restart(self):
        self.app.quit = mock.Mock()
        self.app.change_language("en")
        self.assertEqual(self.settings["language"], "en")
        self.assertTrue(self.app.restart_requested)
        self.app.quit.assert_called_once()

    def test_same_language_does_not_restart(self):
        self.app.quit = mock.Mock()
        self.app.change_language("ru")
        self.assertFalse(self.app.restart_requested)
        self.app.quit.assert_not_called()

    def test_system_choice_resolving_to_current_does_not_restart(self):
        self.app.quit = mock.Mock()
        self.app.change_language("system")
        self.assertFalse(self.app.restart_requested)

    def test_tray_item_switches_language(self):
        self.app.quit = mock.Mock()
        menu = self.app.build_tray_menu()
        item = next(i for i in menu.get_children() if getattr(i, "get_label", lambda: "")() == "Language: English")
        item.activate()
        self.assertEqual(self.settings["language"], "en")
        self.assertTrue(self.app.restart_requested)

    def test_settings_combo_switches_language(self):
        self.app.quit = mock.Mock()
        self.app.open_settings()
        combo = self.app.settings_window.language_combo
        self.assertEqual(combo.get_active_id(), "system")
        combo.set_active_id("en")
        self.assertEqual(self.settings["language"], "en")
        self.assertTrue(self.app.restart_requested)

    def test_main_restarts_after_language_change(self):
        from indicator_sticky_notes import __main__ as entry

        fake = mock.Mock(restart_requested=True)
        fake.run.return_value = 0
        with mock.patch.object(entry, "StickyApp", return_value=fake), \
                mock.patch.object(entry.legacy, "migrate"), \
                mock.patch("os.execv") as execv:
            entry.main()
        execv.assert_called_once()
        self.assertEqual(execv.call_args[0][1][1:], ["-m", "indicator_sticky_notes"])

    def test_main_does_not_restart_normally(self):
        from indicator_sticky_notes import __main__ as entry

        fake = mock.Mock(restart_requested=False)
        fake.run.return_value = 0
        with mock.patch.object(entry, "StickyApp", return_value=fake), \
                mock.patch.object(entry.legacy, "migrate"), \
                mock.patch("os.execv") as execv:
            self.assertEqual(entry.main(), 0)
        execv.assert_not_called()


if __name__ == "__main__":
    unittest.main()
