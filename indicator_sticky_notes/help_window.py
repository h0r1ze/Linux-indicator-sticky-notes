"""Справка (F1) и окно «О программе»."""
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Pango  # noqa: E402

from . import __version__  # noqa: E402
from .i18n import _, N_  # noqa: E402

WEBSITE = "https://github.com/h0r1ze/Linux-indicator-sticky-notes"

# (заголовок, [строки]). Строка «клавиши — действие» оформляется как пункт списка.
HELP_SECTIONS = (
    (N_("Быстрый старт"), (
        N_("Значок в трее: клик показывает или скрывает все заметки, правая кнопка открывает меню."),
        N_("Новая заметка: кнопка «+» в шапке, пункт меню трея или Ctrl+Alt+N из любого места."),
        N_("Закрытие окна заметки только прячет её. Вернуть можно из менеджера или меню трея."),
    )),
    (N_("Шапка заметки"), (
        N_("Перетащите шапку, чтобы переместить заметку; угол ◢ внизу справа меняет размер."),
        N_("Двойной щелчок по шапке сворачивает заметку в одну полоску."),
        N_("● цвет (8 основных, палитра из 32 оттенков и свой цвет), 📌 закрепить поверх окон,"),
        N_("☑ чекбокс в строке, ⋯ меню заметки (правая кнопка по шапке тоже), × в корзину."),
    )),
    (N_("Списки"), (
        N_("Чекбоксы: кнопка ☑ или Ctrl+L; набор «[ ] » превращается в ☐; клик по квадратику ставит галочку."),
        N_("Список с длинным тире: наберите «-» и Tab. Автозамену по «- » (дефис и пробел) можно включить в настройках."),
        N_("Enter продолжает список; на пустом пункте выносит его выше или заканчивает список."),
        N_("Tab и Shift+Tab вкладывают пункт глубже и выше (до трёх уровней)."),
        N_("Backspace сразу за маркером убирает его."),
    )),
    (N_("Текст и шрифт"), (
        N_("Ctrl+B жирный, Ctrl+I курсив, Ctrl+U подчёркнутый, Ctrl+Shift+X зачёркнутый."),
        N_("Размер шрифта: меню ⋯ → «Размер шрифта» (ползунок), Ctrl++, Ctrl+-, Ctrl+0 или Ctrl и колесо мыши."),
        N_("Ctrl+A выделяет весь текст. Сочетания работают и в русской раскладке."),
        N_("Заголовок, прозрачность и группа задаются в меню ⋯ (прозрачность требует композитинга)."),
    )),
    (N_("Менеджер, группы и корзина"), (
        N_("Менеджер заметок: пункт меню трея. Поиск идёт по заголовкам и тексту, найденное подсвечивается в заметке."),
        N_("В списке Ctrl+A выбирает все заметки, Delete отправляет выбранные в корзину."),
        N_("Группы: задаются в меню ⋯; группу целиком можно показать или скрыть из менеджера или трея."),
        N_("Корзина хранит удалённые заметки 30 дней (срок меняется в настройках); пустые заметки удаляются сразу."),
    )),
    (N_("Данные"), (
        N_("Резервные копии: меню трея → «Резервные копии». Автокопия делается раз в сутки при запуске."),
        N_("Синхронизация между компьютерами: в настройках выберите папку Syncthing, Nextcloud и т. п."),
        N_("Экспорт в Markdown и .txt, импорт из .txt, .md, копий и Mint Sticky: меню трея → «Обмен данными»."),
        N_("Заметки лежат в ~/.local/share/indicator-sticky-notes/, настройки в ~/.config/indicator-sticky-notes/."),
    )),
    (N_("Горячие клавиши"), (
        N_("Ctrl+Alt+N новая заметка (глобально, X11; меняется в настройках)"),
        N_("Ctrl+Alt+S показать или скрыть все заметки (глобально, X11)"),
        N_("F1 эта справка"),
        N_("Esc закрывает палитру цветов"),
    )),
)


def help_text() -> str:
    """Справка простым текстом (для тестов и копирования)."""
    parts = []
    for title, lines in HELP_SECTIONS:
        parts.append(_(title))
        parts.extend(f"  {_(line)}" for line in lines)
        parts.append("")
    return "\n".join(parts)


class HelpWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title=_("Справка"))
        self.set_default_size(600, 560)
        view = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD)
        view.set_left_margin(18)
        view.set_right_margin(18)
        view.set_top_margin(12)
        view.set_bottom_margin(12)
        view.set_pixels_below_lines(3)
        buffer = view.get_buffer()
        heading = buffer.create_tag("heading", weight=Pango.Weight.BOLD, scale=1.25,
                                    pixels_above_lines=14, pixels_below_lines=4)
        item = buffer.create_tag("item", left_margin=26, indent=-12)
        for title, lines in HELP_SECTIONS:
            buffer.insert_with_tags(buffer.get_end_iter(), _(title) + "\n", heading)
            for line in lines:
                buffer.insert_with_tags(buffer.get_end_iter(), "•  " + _(line) + "\n", item)
        scroll = Gtk.ScrolledWindow()
        scroll.add(view)
        self.add(scroll)
        self.view = view
        self.connect("delete-event", lambda w, _e: w.hide() or True)
        self.connect("key-press-event", self._on_key)

    def _on_key(self, _widget, event):
        from gi.repository import Gdk

        if event.keyval == Gdk.KEY_Escape:
            self.hide()
            return True
        return False

    def present_window(self):
        self.show_all()
        self.present()


def build_about_dialog(parent=None, icon_name="indicator-sticky-notes"):
    dialog = Gtk.AboutDialog(transient_for=parent, modal=parent is not None)
    dialog.set_program_name(_("Стикеры"))
    dialog.set_version(__version__)
    dialog.set_comments(
        _("Цветные заметки на рабочем столе Linux: чекбоксы, форматирование, группы, "
        "корзина, синхронизация и иконка в трее.")
    )
    dialog.set_website(WEBSITE)
    dialog.set_website_label(_("Страница проекта на GitHub"))
    dialog.set_copyright("© 2026 h0r1ze")
    dialog.set_license_type(Gtk.License.MIT_X11)
    dialog.set_authors(["h0r1ze"])
    dialog.add_credit_section(_("Вдохновлено"), [_("Sticky из Linux Mint")])
    theme = Gtk.IconTheme.get_default()
    dialog.set_logo_icon_name(icon_name if theme.has_icon(icon_name) else "accessories-text-editor")
    return dialog
