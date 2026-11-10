"""Окно одной заметки."""
import re

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import checklist, colors, images, theme  # noqa: E402
from .keys import is_key  # noqa: E402
from .palette import PalettePopup  # noqa: E402
from .storage import Note  # noqa: E402
from .i18n import _, N_  # noqa: E402

SAVE_DELAY_MS = 500
# Пока запускается сеанс (оконный менеджер, панель, настройки экрана), окно могут
# сжать или сдвинуть. Такую геометрию не сохраняем, а потом возвращаем сохранённую.
SETTLE_MS = 30000
SCREEN_SETTLE_MS = 2000  # то же после смены разрешения или мониторов
SNAP_DISTANCE = 24  # на столько пикселей шапку можно поднести к низу другой заметки, чтобы прилипла
EDGE_OUT, EDGE_IN = 10, 5  # зона захвата края: пикселей снаружи листа (в поле тени) и внутри
SNAP_DELAY_MS = 350  # перетаскивание считаем законченным, если окно столько не двигалось
MIN_WIDTH, MIN_HEIGHT = 240, 140
FONT_MIN, FONT_MAX = 8, 40
FONT_RANGE = (FONT_MIN, FONT_MAX)
OPACITIES = (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4)

# Теги форматирования: имя -> свойства Gtk.TextTag. Их диапазоны сохраняются в note.formats.
FORMAT_TAGS = {
    "bold": {"weight": Pango.Weight.BOLD},
    "italic": {"style": Pango.Style.ITALIC},
    "underline": {"underline": Pango.Underline.SINGLE},
    "strike": {"strikethrough": True},
}
FORMAT_LABELS = {
    "bold": N_("Жирный   Ctrl+B"),
    "italic": N_("Курсив   Ctrl+I"),
    "underline": N_("Подчёркнутый   Ctrl+U"),
    "strike": N_("Зачёркнутый   Ctrl+Shift+X"),
}


class NoteWindow(Gtk.Window):
    def __init__(self, note: Note, app):
        super().__init__(title=_("Заметка"))
        self.note = note
        self.app = app
        self.store = app.store
        self._save_source = None
        self._color_class = None
        self._busy = False  # идёт программная правка текста
        self._loading = False  # загрузка/обновление из данных: ничего не сохранять
        self._press = None  # нажатие на шапке: ждём, будет ли это перетаскиванием
        self._typing = {}  # формат для следующих набранных символов: имя -> включён
        self._typing_pos = None
        self._cursors = {}
        self._hang_tags = set()  # имена тегов висячего отступа списков
        self._destroyed = False
        self._settle_source = None
        self._settling = False
        self._drag_source = None  # ждём конца перетаскивания, чтобы проверить «магнит»
        self._last_width = None  # ширину, изменённую пользователем, раздаём всей связке
        self._flash_source = None
        self._font_provider = Gtk.CssProvider()
        self._placeholder_provider = Gtk.CssProvider()

        theme.install()
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_default_size(note.width, note.height)
        self.set_size_request(MIN_WIDTH, MIN_HEIGHT)
        self.set_keep_above(note.pinned)
        self.set_opacity(self._valid_opacity())
        self.get_style_context().add_class("sticky")

        # Скруглённые углы и тень нужны прозрачному окну (есть композитор).
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        self._rounded = visual is not None and screen.is_composited()
        if self._rounded:
            self.set_visual(visual)
            self.set_app_paintable(True)
        margin = theme.SHADOW_MARGIN if self._rounded else 0

        self._palette = PalettePopup(self, self.set_color, self._choose_custom_color)
        self.connect("destroy", self._on_destroy)
        self.connect("hide", self._close_popups)

        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=margin)
        card_style = self.card.get_style_context()
        card_style.add_class("note")
        if not self._rounded:
            card_style.add_class("flat")

        self.card.pack_start(self._build_bar(), False, False, 0)
        self.body = self._build_body()
        self.card.pack_start(self.body, True, True, 0)
        self.grip = self._build_footer()
        self.card.pack_start(self.grip, False, False, 0)
        self.add(self.card)

        self.view.get_style_context().add_provider(
            self._font_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER
        )
        self.placeholder.get_style_context().add_provider(
            self._placeholder_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER
        )
        self._apply_color()
        self._apply_font()
        self._update_collapsed_class()
        self._update_placeholder()
        self._update_pin_button()
        self._update_title_label()
        self._refresh_done_style()
        GLib.idle_add(self._refresh_list_style)
        self.move(note.x, note.y)
        self.connect("configure-event", self._on_configure)
        self.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.connect("motion-notify-event", self._on_edge_motion)
        self.connect("button-press-event", self._on_edge_press)
        self.connect("leave-notify-event", lambda *_a: self._show_edge_cursor(None))
        self._edge_cursor = None
        self.card.connect("size-allocate", lambda *_a: self.update_input_shape())
        self.connect("key-press-event", self._on_window_key)
        self.connect("delete-event", self._on_close)
        self.connect("map", lambda _w: self._apply_collapsed())
        self._screen_handlers = [
            screen.connect(signal, lambda *_a: self._settle(SCREEN_SETTLE_MS))
            for signal in ("size-changed", "monitors-changed")
        ]
        self._settle(SETTLE_MS)

    # --- построение интерфейса ---

    def _build_bar(self):
        handle = Gtk.EventBox()
        handle.set_visible_window(False)
        handle.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.BUTTON1_MOTION_MASK
        )
        handle.connect("button-press-event", self._on_bar_press)
        handle.connect("button-release-event", lambda *_a: setattr(self, "_press", None))
        handle.connect("motion-notify-event", self._on_bar_motion)

        bar = Gtk.Box(spacing=2)
        bar.get_style_context().add_class("bar")

        add = self._flat_button("+", _("Новая заметка"))
        add.connect("clicked", lambda _b: self.app.new_note())
        bar.pack_start(add, False, False, 0)

        palette = self._flat_button("●", _("Цвет"))
        palette.connect("clicked", lambda button: self._palette.toggle(button))
        bar.pack_start(palette, False, False, 0)

        self.pin_button = self._flat_button("📌", _("Закрепить поверх всех окон"))
        self.pin_button.get_style_context().add_class("pin")
        self.pin_button.connect("clicked", lambda _b: self.set_pinned(not self.note.pinned))
        bar.pack_start(self.pin_button, False, False, 0)

        self.title_label = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
        self.title_label.get_style_context().add_class("title")
        bar.pack_start(self.title_label, True, True, 0)

        delete = self._flat_button("×", _("В корзину"))
        delete.get_style_context().add_class("danger")
        delete.connect("clicked", lambda _b: self.app.delete_note(self.note.id))
        bar.pack_end(delete, False, False, 0)

        self.collapse_button = self._flat_button("", _("Свернуть"))
        # Шеврон рисуем сами: символы ▴/˄ в разных шрифтах разного размера и высоты.
        self.collapse_button.remove(self.collapse_button.get_child())
        chevron = Gtk.DrawingArea()
        chevron.set_size_request(12, 12)
        chevron.connect("draw", self._draw_chevron)
        self.collapse_button.add(chevron)
        self.collapse_button.connect("clicked", lambda _b: self.set_collapsed(not self.note.collapsed))
        bar.pack_end(self.collapse_button, False, False, 0)

        self.unlink_button = self._flat_button("", _("Разъединить связку"))
        self.unlink_button.remove(self.unlink_button.get_child())
        links = Gtk.DrawingArea()
        links.set_size_request(14, 12)
        links.connect("draw", self._draw_links)
        self.unlink_button.add(links)
        self.unlink_button.set_no_show_all(True)  # видна только у заметок в связке
        links.show()
        self.unlink_button.connect("clicked", lambda _b: self.app.unlink_stack(self.note.id))
        bar.pack_end(self.unlink_button, False, False, 0)

        self.menu_button = self._flat_button("⋯", _("Меню заметки"))
        self.menu_button.connect("clicked", lambda _b: self.popup_menu())
        bar.pack_end(self.menu_button, False, False, 0)

        handle.add(bar)
        return handle

    def _build_body(self):
        self.view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.view.set_left_margin(14)
        self.view.set_right_margin(14)
        self.view.set_top_margin(10)
        self.view.set_bottom_margin(6)
        self.view.set_pixels_below_lines(3)
        self.view.add_events(Gdk.EventMask.SCROLL_MASK)
        buffer = self.view.get_buffer()
        self._loading = True
        buffer.set_text(self.note.text)
        self._apply_saved_images()
        self.done_tag = buffer.create_tag("done", strikethrough=True)
        for name, props in FORMAT_TAGS.items():
            buffer.create_tag(name, **props)
        self.found_tag = buffer.create_tag(
            "found", background_rgba=Gdk.RGBA(1.0, 0.84, 0.0, 0.6), foreground="#000000"
        )
        self._apply_saved_formats()
        self._loading = False
        buffer.connect("changed", self._on_text_changed)
        buffer.connect("apply-tag", self._on_tags_changed)
        buffer.connect("remove-tag", self._on_tags_changed)
        buffer.connect_after("insert-text", self._on_insert_text)
        self.view.connect("key-press-event", self._on_key_press)
        self.view.connect("button-press-event", self._on_view_press)
        self.view.connect_after("motion-notify-event", self._on_view_motion)
        self.view.connect("scroll-event", self._on_scroll)
        self.view.connect("paste-clipboard", self._on_paste)
        targets = self.view.drag_dest_get_target_list() or Gtk.TargetList.new([])
        targets.add_uri_targets(0)
        self.view.drag_dest_set_target_list(targets)
        self.view.connect("drag-data-received", self._on_drag_received)

        scroll = Gtk.ScrolledWindow()
        # EXTERNAL, а не NEVER: иначе минимальная ширина окна равна самой
        # длинной строке текста без переносов.
        scroll.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.view)

        self.placeholder = Gtk.Label(label=_("Напишите что-нибудь…"))
        self.placeholder.get_style_context().add_class("placeholder")
        self.placeholder.set_halign(Gtk.Align.START)
        self.placeholder.set_valign(Gtk.Align.START)
        self.placeholder.set_margin_start(14)
        self.placeholder.set_margin_top(10)
        self.placeholder.set_no_show_all(True)  # видимостью управляет _update_placeholder

        overlay = Gtk.Overlay()
        overlay.add(scroll)
        overlay.add_overlay(self.placeholder)
        overlay.set_overlay_pass_through(self.placeholder, True)
        return overlay

    def _build_footer(self):
        """Нижняя панель: форматирование, чекбокс, размер шрифта и уголок растягивания."""
        footer = Gtk.Box(spacing=0)
        footer.get_style_context().add_class("footer")
        # Кнопки не забирают фокус: иначе пропадёт выделение, к которому применяется формат.
        for name, label, markup in (
            ("bold", "B", "<b>B</b>"),
            ("italic", "I", "<i>I</i>"),
            ("underline", "U", "<u>U</u>"),
            ("strike", "S", "<s>S</s>"),
        ):
            button = self._tool_button(markup, _(FORMAT_LABELS[name]))
            button.connect("clicked", lambda _b, n=name: self.toggle_format(n))
            footer.pack_start(button, False, False, 0)
        footer.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 4)
        check = self._tool_button("☑", _("Чекбокс в строке (Ctrl+L)"))
        check.connect("clicked", lambda _b: self.toggle_checklist())
        footer.pack_start(check, False, False, 0)
        for markup, tooltip, delta in (("A<sup>−</sup>", _("Мельче (Ctrl+-)"), -1),
                                       ("A<sup>+</sup>", _("Крупнее (Ctrl++)"), 1)):
            button = self._tool_button(markup, tooltip)
            button.connect("clicked", lambda _b, d=delta: self.change_font(d))
            footer.pack_start(button, False, False, 0)
        picture = self._tool_button("🖼", _("Вставить картинку (или Ctrl+V, перетаскивание файла)"))
        picture.connect("clicked", lambda _b: self.choose_image())
        footer.pack_start(picture, False, False, 0)
        footer.pack_end(self._build_grip(), False, False, 0)
        self.solo_button = self._tool_button("", "")
        self.solo_button.remove(self.solo_button.get_child())
        magnet = Gtk.DrawingArea()
        magnet.set_size_request(14, 14)
        magnet.connect("draw", self._draw_magnet)
        self.solo_button.add(magnet)
        self.solo_button.connect("clicked", lambda _b: self.app.set_solo(self.note.id, not self.note.solo))
        footer.pack_end(self.solo_button, False, False, 0)
        self._update_solo_button()
        return footer

    def _tool_button(self, markup, tooltip):
        button = self._flat_button("", tooltip)
        button.get_child().set_markup(markup)
        button.set_focus_on_click(False)
        return button

    def _build_grip(self):
        grip = Gtk.EventBox()
        grip.set_visible_window(False)
        grip.set_size_request(22, -1)
        grip.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.ENTER_NOTIFY_MASK
            | Gdk.EventMask.LEAVE_NOTIFY_MASK
        )
        grip.connect("button-press-event", self._on_grip_press)
        # У EventBox без видимого окна нет своего GdkWindow, поэтому курсор ставим на
        # окно заметки по входу/выходу: иначе он остался бы на всей заметке.
        grip.connect("enter-notify-event", lambda *_a: self._set_window_cursor("se-resize"))
        grip.connect("leave-notify-event", lambda *_a: self._set_window_cursor(None))
        label = Gtk.Label(label="◢", halign=Gtk.Align.END, valign=Gtk.Align.END, margin_end=6)
        label.get_style_context().add_class("grip")
        grip.add(label)
        return grip

    def _cursor(self, name):
        if name not in self._cursors:
            self._cursors[name] = Gdk.Cursor.new_from_name(self.get_display(), name)
        return self._cursors[name]

    # --- растягивание за края (и у свёрнутой заметки — по ширине) ---

    _EDGE_CURSORS = {
        Gdk.WindowEdge.WEST: "w-resize", Gdk.WindowEdge.EAST: "e-resize",
        Gdk.WindowEdge.SOUTH: "s-resize", Gdk.WindowEdge.SOUTH_WEST: "sw-resize",
        Gdk.WindowEdge.SOUTH_EAST: "se-resize",
    }

    def edge_at(self, x_root, y_root):
        """Край листа под точкой экрана: Gdk.WindowEdge или None."""
        gdk_window = self.get_window()
        if gdk_window is None:
            return None
        ox, oy = gdk_window.get_origin()[1:]
        x, y = x_root - ox, y_root - oy
        box = self.card.get_allocation()
        left, right = box.x, box.x + box.width
        top, bottom = box.y, box.y + box.height
        if not (top <= y <= bottom + EDGE_OUT) or not (left - EDGE_OUT <= x <= right + EDGE_OUT):
            return None
        west = x <= left + EDGE_IN
        east = x >= right - EDGE_IN
        south = not self.note.collapsed and y >= bottom - EDGE_IN
        if south:
            return Gdk.WindowEdge.SOUTH_WEST if west else Gdk.WindowEdge.SOUTH_EAST if east \
                else Gdk.WindowEdge.SOUTH
        if y > bottom:
            return None
        return Gdk.WindowEdge.WEST if west else Gdk.WindowEdge.EAST if east else None

    def update_input_shape(self):
        """Прозрачное поле под тень не ловит мышь (иначе соседняя заметка связки закрывает
        уголок растягивания), кроме узкой зоны захвата краёв слева, справа и снизу."""
        gdk_window = self.get_window()
        if gdk_window is None or not self._rounded:
            return
        box = self.card.get_allocation()
        below = EDGE_OUT
        if self.note.collapsed or self.card.get_style_context().has_class("stack-above"):
            below = 0  # снизу вплотную висит другая заметка (или это одна шапка)
        rect = cairo.RectangleInt(box.x - EDGE_OUT, box.y,
                                  box.width + 2 * EDGE_OUT, box.height + below)
        gdk_window.input_shape_combine_region(cairo.Region(rect), 0, 0)

    def _show_edge_cursor(self, edge):
        name = self._EDGE_CURSORS.get(edge)
        if name != self._edge_cursor:
            self._edge_cursor = name
            self._set_window_cursor(name)

    def _on_edge_motion(self, _widget, event):
        if not event.state & Gdk.ModifierType.BUTTON1_MASK:
            self._show_edge_cursor(self.edge_at(event.x_root, event.y_root))
        return False

    def _on_edge_press(self, _widget, event):
        if event.button != 1 or event.type != Gdk.EventType.BUTTON_PRESS:
            return False
        edge = self.edge_at(event.x_root, event.y_root)
        if edge is None:
            return False
        self._press = None  # это не перетаскивание за шапку
        self._stop_settling()
        self.begin_resize_drag(edge, event.button, int(event.x_root), int(event.y_root), event.time)
        return True

    def _set_window_cursor(self, name):
        gdk_window = self.get_window()
        if gdk_window is not None:
            gdk_window.set_cursor(self._cursor(name) if name else None)

    @staticmethod
    def _flat_button(label, tooltip):
        button = Gtk.Button(label=label)
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_tooltip_text(tooltip)
        return button

    # --- события окна ---

    def _on_bar_press(self, _widget, event):
        if event.button == 3:
            self.popup_menu()
            return True
        if event.button != 1:
            return False
        if event.type == Gdk.EventType.DOUBLE_BUTTON_PRESS:
            self._press = None
            self.set_collapsed(not self.note.collapsed)
            return True
        self._press = (event.x_root, event.y_root)
        return False

    def _on_bar_motion(self, _widget, event):
        # Перетаскивание начинаем только когда мышь сдвинулась: иначе двойной щелчок
        # по шапке не дойдёт до нас (оконный менеджер перехватит нажатие).
        if self._press is None:
            return False
        if abs(event.x_root - self._press[0]) + abs(event.y_root - self._press[1]) > 4:
            self._press = None
            self._stop_settling()
            # Связку тянем целиком: двигаем верхнюю заметку, остальные едут за ней.
            root = self.app.stack_root(self)
            root._stop_settling()
            root._start_drag_watch()
            root.begin_move_drag(1, int(event.x_root), int(event.y_root), event.time)
        return True

    def _on_grip_press(self, _widget, event):
        if event.button == 1:
            self._stop_settling()
            self.begin_resize_drag(
                Gdk.WindowEdge.SOUTH_EAST,
                event.button,
                int(event.x_root),
                int(event.y_root),
                event.time,
            )
        return True

    def _settle(self, delay):
        """Не сохранять геометрию delay мс, затем вернуть сохранённую (как «свернуть-развернуть»)."""
        if self._settle_source is not None:
            GLib.source_remove(self._settle_source)
        self._settling = True
        self._settle_source = GLib.timeout_add(delay, self._end_settle)

    def _stop_settling(self):
        """Пользователь сам двигает или тянет окно: его геометрию сохраняем сразу."""
        if self._settle_source is not None:
            GLib.source_remove(self._settle_source)
            self._settle_source = None
        self._settling = False

    def _end_settle(self):
        self._settle_source = None
        self._settling = False
        if not self._destroyed and self.get_visible():
            self.move(self.note.x, self.note.y)
            self._apply_collapsed()
        return False

    def _on_configure(self, _widget, _event):
        self.layout_stack()
        width = self.get_size()[0]
        if self._last_width is not None and width != self._last_width:
            self.app.sync_stack_width(self, width, self.get_position()[0])
        self._last_width = width
        if self._drag_source is not None:
            self._start_drag_watch()
            self.app.show_snap_target(self.snap_target())
        if self._settling:
            return False
        x, y = self.get_position()
        width, height = self.get_size()
        self.note.x, self.note.y = x, y
        self.note.width = width
        if not self.note.collapsed:  # высота свёрнутой заметки — не её настоящий размер
            self.note.height = height
        self._schedule_save(touch=False)
        return False

    def _on_window_key(self, _widget, event):
        """F1 открывает справку при любом фокусе в окне заметки."""
        if event.keyval == Gdk.KEY_F1:
            self.app.open_help()
            return True
        return False

    def _on_destroy(self, _widget):
        self._destroyed = True
        self._stop_settling()
        for source in (self._drag_source, self._flash_source):
            if source is not None:
                GLib.source_remove(source)
        self._drag_source = self._flash_source = None
        screen = self.get_screen()
        for handler in self._screen_handlers:
            screen.disconnect(handler)
        # Отложенную запись отменяем: заметка уже могла уйти в корзину.
        if self._save_source is not None:
            GLib.source_remove(self._save_source)
            self._save_source = None
        self._palette.destroy()

    def _close_popups(self, _widget=None):
        self._palette.close_popup()

    def _on_close(self, _widget, _event):
        # Закрытие окна только прячет заметку; удаляется она кнопкой.
        self.hide_note()
        return True

    # --- показать / спрятать / закрепить / свернуть ---

    def show_note(self, highlight=None):
        was_hidden = self.note.hidden
        self.note.hidden = False
        self.show_all()
        self.present()
        if was_hidden:
            self._schedule_save(touch=False)
        if highlight is not None:
            self.highlight(highlight)

    def hide_note(self):
        self.note.hidden = True
        self.hide()
        self.flush()

    def set_pinned(self, pinned):
        self.note.pinned = bool(pinned)
        self.set_keep_above(self.note.pinned)
        self._update_pin_button()
        self._schedule_save()

    def _update_pin_button(self):
        ctx = self.pin_button.get_style_context()
        if self.note.pinned:
            ctx.add_class("active")
        else:
            ctx.remove_class("active")
        self.pin_button.set_tooltip_text(
            _("Открепить") if self.note.pinned else _("Закрепить поверх всех окон")
        )

    def set_collapsed(self, collapsed):
        self.note.collapsed = bool(collapsed)
        self._apply_collapsed()
        self._update_title_label()
        self._schedule_save(touch=False)

    def _apply_collapsed(self):
        collapsed = self.note.collapsed
        self._update_collapsed_class()
        self.body.set_visible(not collapsed)
        self.grip.set_visible(not collapsed)
        self.set_size_request(MIN_WIDTH, 1 if collapsed else MIN_HEIGHT)
        if collapsed:
            self.resize(max(self.note.width, MIN_WIDTH), 1)
        else:
            self.resize(max(self.note.width, MIN_WIDTH), max(self.note.height, MIN_HEIGHT))

    # --- связка ---

    def layout_stack(self):
        """Прикреплённую снизу заметку поставить вплотную под эту."""
        child = self.app.dock_child(self.note.id)
        if child is None or not self.get_visible() or not child.get_visible():
            return
        x, y = self.get_position()
        height = self.get_size()[1]
        margin = theme.SHADOW_MARGIN if self._rounded else 0
        target = (x, y + height - 2 * margin)
        if tuple(child.get_position()) != target:
            child.move(*target)

    def _start_drag_watch(self):
        if self._drag_source is not None:
            GLib.source_remove(self._drag_source)
        self._drag_source = GLib.timeout_add(SNAP_DELAY_MS, self._end_drag)

    def _end_drag(self):
        self._drag_source = None
        self.app.show_snap_target(None)
        if not self._destroyed:
            self.try_snap()
        return False

    def try_snap(self):
        """«Магнит»: шапка рядом с низом другой заметки — прикрепиться к ней. True, если прилипла."""
        target = self.snap_target()
        return self.app.dock(self.note.id, target.note.id) if target is not None else False

    def snap_target(self):
        """Заметка, к низу которой прилипнет эта, если отпустить её сейчас."""
        if self.note.dock or self.note.solo or not self.get_visible():
            return None
        margin = theme.SHADOW_MARGIN if self._rounded else 0
        x, y = self.get_position()
        own = self.app.stack_members(self)
        for other in list(self.app.windows.values()):
            if other in own or other.note.solo or not other.get_visible() \
                    or self.app.dock_child(other.note.id):
                continue
            ox, oy = other.get_position()
            bottom = oy + other.get_size()[1] - 2 * margin
            if abs(y - bottom) <= SNAP_DISTANCE and abs(x - ox) <= SNAP_DISTANCE * 3:
                return other
        return None

    def _update_solo_button(self):
        ctx = self.solo_button.get_style_context()
        if self.note.solo:
            ctx.add_class("active")
            self.solo_button.set_tooltip_text(_("Отдельная заметка: нажмите, чтобы её снова можно было скреплять"))
        else:
            ctx.remove_class("active")
            self.solo_button.set_tooltip_text(_("Сделать отдельной: не скреплять с другими заметками"))
        self.solo_button.queue_draw()

    def _draw_magnet(self, area, cr):
        """Подкова-магнит; у отдельной заметки перечёркнута."""
        color = self.solo_button.get_style_context().get_color(self.solo_button.get_state_flags())
        width, height = area.get_allocated_width(), area.get_allocated_height()
        cx, cy = width / 2, height / 2
        cr.set_source_rgba(color.red, color.green, color.blue, color.alpha)
        cr.set_line_width(2)
        cr.set_line_cap(1)  # cairo.LINE_CAP_ROUND
        cr.move_to(cx - 4.5, cy - 5)
        cr.line_to(cx - 4.5, cy)
        cr.arc_negative(cx, cy, 4.5, 3.1416, 0)
        cr.line_to(cx + 4.5, cy - 5)
        cr.stroke()
        if self.note.solo:
            cr.move_to(cx - 6, cy + 6)
            cr.line_to(cx + 6, cy - 6)
            cr.stroke()
        return False

    def update_unlink_button(self):
        """Кнопка-цепочка и вид связки: стыкующиеся углы прямые, листы сливаются в один."""
        above = self.note.dock in self.app.windows
        below = self.app.dock_child(self.note.id) is not None
        self.unlink_button.set_visible(above or below)
        self._update_solo_button()
        ctx = self.card.get_style_context()
        for name, on in (("stack-above", below), ("stack-below", above)):
            if on:
                ctx.add_class(name)
            else:
                ctx.remove_class(name)
        self.update_input_shape()

    def set_card_class(self, name, on):
        ctx = self.card.get_style_context()
        if on:
            ctx.add_class(name)
        else:
            ctx.remove_class(name)

    def flash(self):
        """Короткая подсветка: заметка только что вошла в связку."""
        self.set_card_class("snapped", True)
        if self._flash_source is not None:
            GLib.source_remove(self._flash_source)

        def done():
            self._flash_source = None
            if not self._destroyed:
                self.set_card_class("snapped", False)
            return False
        self._flash_source = GLib.timeout_add(700, done)

    def _draw_links(self, area, cr):
        """Два звена цепочки цветом кнопок шапки."""
        color = self.unlink_button.get_style_context().get_color(self.unlink_button.get_state_flags())
        width, height = area.get_allocated_width(), area.get_allocated_height()
        cr.set_source_rgba(color.red, color.green, color.blue, color.alpha)
        cr.set_line_width(1.8)
        link_w, link_h, radius = 8, 5, 2.5
        for dx in (-2.5, 2.5):
            left = width / 2 + dx - link_w / 2
            top = height / 2 - link_h / 2
            cr.new_sub_path()
            cr.arc(left + link_w - radius, top + radius, radius, -1.5708, 0)
            cr.arc(left + link_w - radius, top + link_h - radius, radius, 0, 1.5708)
            cr.arc(left + radius, top + link_h - radius, radius, 1.5708, 3.1416)
            cr.arc(left + radius, top + radius, radius, 3.1416, 4.7124)
            cr.close_path()
        cr.stroke()
        return False

    def _draw_chevron(self, area, cr):
        """Галочка ˄ (свернуть) или ˅ (развернуть) цветом и толщиной как у ×."""
        color = self.collapse_button.get_style_context().get_color(
            self.collapse_button.get_state_flags()
        )
        width, height = area.get_allocated_width(), area.get_allocated_height()
        half, rise = 5, 3
        cx, cy = width / 2, height / 2
        tip = -rise if not self.note.collapsed else rise
        cr.set_source_rgba(color.red, color.green, color.blue, color.alpha)
        cr.set_line_width(2)
        cr.set_line_cap(1)  # cairo.LINE_CAP_ROUND
        cr.set_line_join(1)  # cairo.LINE_JOIN_ROUND
        cr.move_to(cx - half, cy - tip)
        cr.line_to(cx, cy + tip)
        cr.line_to(cx + half, cy - tip)
        cr.stroke()
        return False

    def _update_collapsed_class(self):
        """У свёрнутой заметки скруглены все углы шапки, а не только верхние."""
        ctx = self.card.get_style_context()
        if self.note.collapsed:
            ctx.add_class("collapsed")
        else:
            ctx.remove_class("collapsed")
        self.collapse_button.queue_draw()
        self.collapse_button.set_tooltip_text(_("Развернуть") if self.note.collapsed else _("Свернуть"))

    # --- заголовок, прозрачность, размер шрифта, группа ---

    def _update_title_label(self):
        text = self.note.title.strip()
        if not text and self.note.collapsed:
            text = self.note.preview(40)
        self.title_label.set_text(text)

    def _ask_text(self, title, placeholder, initial=""):
        """Небольшое окно с одним полем ввода. Возвращает строку или None при отмене."""
        dialog = Gtk.Dialog(title=title, transient_for=self, modal=True)
        dialog.add_buttons(_("Отмена"), Gtk.ResponseType.CANCEL, _("Готово"), Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        entry = Gtk.Entry(text=initial, activates_default=True, width_chars=32,
                          placeholder_text=placeholder)
        for side in ("start", "end", "top"):
            getattr(entry, f"set_margin_{side}")(12)
        entry.set_margin_bottom(6)
        dialog.get_content_area().add(entry)
        dialog.show_all()
        answer = entry.get_text() if dialog.run() == Gtk.ResponseType.OK else None
        dialog.destroy()
        return answer

    def edit_title(self):
        title = self._ask_text(_("Заголовок заметки"), _("Заголовок"), self.note.title)
        if title is not None:
            self.set_title_text(title)

    def set_title_text(self, title):
        self.note.title = title.strip()
        self._update_title_label()
        self._schedule_save()

    def ask_new_group(self):
        group = self._ask_text(_("Новая группа"), _("Название группы"))
        if group and group.strip():
            self.set_group(group)

    def _valid_opacity(self):
        value = self.note.opacity
        ok = isinstance(value, (int, float)) and not isinstance(value, bool) and 0.2 <= value <= 1.0
        return float(value) if ok else 1.0

    def set_note_opacity(self, value):
        self.note.opacity = float(value)
        self.set_opacity(self._valid_opacity())  # нужен композитор; без него не виден
        self._schedule_save()

    def effective_font_size(self):
        return self.note.font_size or self.app.default_font_size()

    def change_font(self, delta):
        """delta=0 — вернуть размер по умолчанию."""
        if delta == 0:
            self.note.font_size = 0
            self._apply_font()
            self._schedule_save()
        else:
            self.set_font_size(self.effective_font_size() + delta)

    def set_font_size(self, size):
        """Задать размер шрифта в пунктах (в пределах FONT_RANGE)."""
        self.note.font_size = max(FONT_RANGE[0], min(FONT_RANGE[1], int(size)))
        self._apply_font()
        self._schedule_save()

    def _apply_font(self):
        size = int(self.note.font_size or 0)
        if size:
            view_css = f"textview, textview text {{ font-size: {size}pt; }}"
            placeholder_css = f"label {{ font-size: {size}pt; }}"
        else:
            view_css = placeholder_css = ""
        self._font_provider.load_from_data(view_css.encode())
        self._placeholder_provider.load_from_data(placeholder_css.encode())
        GLib.idle_add(self._refresh_list_style)  # ширина маркера зависит от шрифта

    def set_group(self, group):
        self.note.group = group.strip()
        self._schedule_save()

    def _font_slider_item(self):
        """Пункт меню с ползунком размера шрифта.

        Меню GTK забирает события мыши себе и до вложенного ползунка их не доводит,
        поэтому перетаскивание ведёт _bind_slider_drag.
        """
        item = Gtk.MenuItem()
        box = Gtk.Box(spacing=8, margin_start=6, margin_end=6, margin_top=4, margin_bottom=4)
        small = Gtk.Label()
        small.set_markup('<span size="small">A</span>')
        box.pack_start(small, False, False, 0)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, FONT_MIN, FONT_MAX, 1)
        scale.set_draw_value(False)
        scale.set_size_request(190, -1)
        scale.set_value(self.effective_font_size())
        scale.add_mark(self.app.default_font_size(), Gtk.PositionType.BOTTOM, None)  # «по умолчанию»
        scale.set_tooltip_text(_("Размер шрифта: потяните ползунок (отметка — размер по умолчанию)"))
        box.pack_start(scale, True, True, 0)
        big = Gtk.Label()
        big.set_markup('<span size="x-large">A</span>')
        box.pack_start(big, False, False, 0)
        value = Gtk.Label(label=_("{size} пт").format(size=self.effective_font_size()), width_chars=5, xalign=1)
        box.pack_start(value, False, False, 0)

        def on_change(widget):
            size = int(round(widget.get_value()))
            value.set_text(_("{size} пт").format(size=size))
            self.set_font_size(size)

        scale.connect("value-changed", on_change)
        item.add(box)
        item.font_scale = scale  # для тестов
        return item

    @staticmethod
    def _bind_slider_drag(item, shells):
        """Перетаскивание ползунка внутри открытого меню.

        Нажатие над дорожкой ставит значение по положению указателя, движение с зажатой
        кнопкой ведёт ползунок (даже за границами меню), отпускание гасится, чтобы меню
        не закрылось как после обычного выбора пункта.
        """
        scale = item.font_scale
        dragging = {"on": False}

        def geometry():
            toplevel = item.get_toplevel()
            gdk_window = toplevel.get_window()
            if gdk_window is None:
                return None
            ox, oy = gdk_window.get_origin()[1:]
            tx, ty = scale.translate_coordinates(toplevel, 0, 0)
            return ox + tx, oy + ty

        def set_from_pointer(event):
            origin = geometry()
            if origin is None:
                return
            rect = scale.get_range_rect()
            start, end = scale.get_slider_range()
            knob = max(end - start, 1)
            span = max(rect.width - knob, 1)
            fraction = (event.x_root - (origin[0] + rect.x + knob / 2)) / span
            adj = scale.get_adjustment()
            top = adj.get_upper() - adj.get_page_size()
            scale.set_value(round(adj.get_lower() + min(1, max(0, fraction)) * (top - adj.get_lower())))

        def on_press(_widget, event):
            origin = geometry()
            if event.button != 1 or origin is None:
                return False
            inside = (origin[0] <= event.x_root < origin[0] + scale.get_allocated_width()
                      and origin[1] <= event.y_root < origin[1] + scale.get_allocated_height())
            if not inside:
                return False
            dragging["on"] = True
            set_from_pointer(event)
            return True

        def on_motion(_widget, event):
            if not dragging["on"]:
                return False
            set_from_pointer(event)
            return True

        def on_release(_widget, _event):
            if not dragging["on"]:
                return False
            dragging["on"] = False
            return True

        item.connect("button-press-event", on_press)
        for widget in (item, *shells):  # указатель может уйти за пределы пункта
            widget.connect("motion-notify-event", on_motion)
            widget.connect("button-release-event", on_release)

    # --- меню «⋯» ---

    def popup_menu(self):
        menu = self.build_menu()
        menu.popup_at_widget(
            self.menu_button, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None
        )

    def build_menu(self):
        menu = Gtk.Menu()

        def item(parent, label, callback, check=None):
            if check is None:
                entry = Gtk.MenuItem(label=label)
                entry.connect("activate", lambda _i: callback())
            else:
                entry = Gtk.CheckMenuItem(label=label)
                entry.set_active(check)
                entry.connect("toggled", lambda _i: callback())
            parent.append(entry)
            return entry

        def submenu(label):
            sub = Gtk.Menu()
            head = Gtk.MenuItem(label=label)
            head.set_submenu(sub)
            menu.append(head)
            return sub

        item(menu, _("Заголовок…"), self.edit_title)
        item(menu, _("Развернуть") if self.note.collapsed else _("Свернуть"),
             lambda: self.set_collapsed(not self.note.collapsed))
        item(menu, _("Отдельная (не скреплять с другими)"),
             lambda: self.app.set_solo(self.note.id, not self.note.solo), check=self.note.solo)
        menu.append(Gtk.SeparatorMenuItem())

        formats = submenu(_("Формат"))
        for name, label in FORMAT_LABELS.items():
            label = _(label)
            item(formats, label, lambda n=name: self.toggle_format(n),
                 check=self.format_state(name))
        formats.append(Gtk.SeparatorMenuItem())
        item(formats, _("Чекбокс   Ctrl+L"), self.toggle_checklist)

        font = submenu(_("Размер шрифта"))
        slider = self._font_slider_item()
        font.append(slider)
        self._bind_slider_drag(slider, (menu, font))
        font.append(Gtk.SeparatorMenuItem())
        item(font, _("По умолчанию ({size} пт)   Ctrl+0").format(size=self.app.default_font_size()),
             lambda: self.change_font(0))

        opacity = submenu(_("Прозрачность"))
        for value in OPACITIES:
            item(opacity, f"{int(value * 100)}%", lambda v=value: self.set_note_opacity(v),
                 check=abs(self._valid_opacity() - value) < 0.01)

        groups = submenu(_("Группа"))
        item(groups, _("Без группы"), lambda: self.set_group(""), check=not self.note.group)
        for name in self.store.groups():
            item(groups, name, lambda n=name: self.set_group(n), check=self.note.group == name)
        groups.append(Gtk.SeparatorMenuItem())
        item(groups, _("Новая группа…"), self.ask_new_group)

        menu.append(Gtk.SeparatorMenuItem())
        item(menu, _("Сохранить как файл…"), lambda: self.app.export_note(self.note, self))
        item(menu, _("В корзину"), lambda: self.app.delete_note(self.note.id))

        # То же, что в меню трея: пригодится там, где значка в трее нет (GNOME без расширения).
        menu.append(Gtk.SeparatorMenuItem())
        app_item = Gtk.MenuItem(label=_("Стикеры"))
        app_item.set_submenu(self.app.build_tray_menu())
        menu.append(app_item)
        menu.show_all()
        return menu

    # --- цвет ---

    def _choose_custom_color(self):
        dialog = Gtk.ColorChooserDialog(title=_("Свой цвет"), transient_for=self)
        dialog.set_use_alpha(False)
        dialog.set_property("show-editor", True)
        current = Gdk.RGBA()
        current.parse(self._current_body())
        dialog.set_rgba(current)
        if dialog.run() == Gtk.ResponseType.OK:
            rgba = dialog.get_rgba()
            self.set_color(colors.to_hex((rgba.red * 255, rgba.green * 255, rgba.blue * 255)))
        dialog.destroy()

    def set_color(self, name):
        self.note.color = name
        self._apply_color()
        self._schedule_save()

    def _current_body(self):
        color = theme.style_class(self.note.color)
        return theme.PALETTE[color][0] if color in theme.PALETTE else color

    def _apply_color(self):
        self.note.color = theme.style_class(self.note.color)
        ctx = self.card.get_style_context()
        if self._color_class:
            ctx.remove_class(self._color_class)
        self._color_class = theme.css_class_for(self.note.color)
        ctx.add_class(self._color_class)
        # Выполненные пункты бледнеют относительно цвета текста на этом фоне.
        text = Gdk.RGBA()
        text.parse(colors.text_color_for(self._current_body()))
        text.alpha = 0.5
        self.done_tag.set_property("foreground-rgba", text)

    # --- текст ---

    def _on_text_changed(self, buffer):
        if self._loading:
            return
        start, end = buffer.get_bounds()
        self.note.text = buffer.get_slice(start, end, True)
        self._update_placeholder()
        self._update_title_label()
        if not self._busy:
            GLib.idle_add(self._convert_prefix)
        self._refresh_done_style()
        self._refresh_list_style()
        self._clear_highlight()
        self._schedule_save()

    def _update_placeholder(self):
        self.placeholder.set_visible(not self.note.text)

    def _text(self):
        buffer = self.view.get_buffer()
        return buffer.get_slice(*buffer.get_bounds(), True)

    # --- картинки ---

    @property
    def images_dir(self):
        return images.images_dir(self.store.path)

    def _thumb_width(self):
        return max(60, min(images.THUMB_MAX, self.note.width - 2 * theme.SHADOW_MARGIN - 40))

    def _apply_saved_images(self):
        """Символы картинок из note.text заменить миниатюрами."""
        buffer = self.view.get_buffer()
        for offset, name in sorted(self.note.images, key=lambda item: item[0]):
            it = buffer.get_iter_at_offset(offset)
            if it.get_char() != images.IMAGE_CHAR or it.get_pixbuf() is not None:
                continue
            after = it.copy()
            after.forward_char()
            buffer.delete(it, after)
            buffer.insert_pixbuf(it, images.thumbnail(self.images_dir, name, self._thumb_width()))

    def collect_images(self):
        """[[смещение, имя файла], ...] для всех картинок в тексте."""
        buffer = self.view.get_buffer()
        result = []
        for offset, char in enumerate(self._text()):
            if char == images.IMAGE_CHAR:
                name = images.name_of(buffer.get_iter_at_offset(offset).get_pixbuf())
                if name:
                    result.append([offset, name])
        return result

    def insert_image(self, name, where=None):
        """Вставить картинку (уже лежащую в папке images/) в позицию курсора или where."""
        buffer = self.view.get_buffer()
        if where is None and buffer.get_has_selection():
            buffer.delete_selection(True, True)
        it = where if where is not None else buffer.get_iter_at_mark(buffer.get_insert())
        buffer.insert_pixbuf(it, images.thumbnail(self.images_dir, name, self._thumb_width()))
        buffer.place_cursor(it)
        self.note.images = self.collect_images()
        self._schedule_save()

    def insert_image_files(self, paths, where=None):
        """Скопировать файлы-картинки в папку заметок и вставить. Возвращает число вставленных."""
        count = 0
        buffer = self.view.get_buffer()
        mark = buffer.create_mark(None, where, False) if where is not None else None
        for path in paths:
            if not images.is_image_file(path):
                continue
            try:
                name = images.import_file(path, self.images_dir)
            except OSError:
                continue
            self.insert_image(name, buffer.get_iter_at_mark(mark) if mark else None)
            count += 1
        if mark is not None:
            buffer.delete_mark(mark)
        return count

    def _on_paste(self, view):
        """Ctrl+V: файлы-картинки и изображения из буфера обмена вставляются картинками."""
        clipboard = view.get_clipboard(Gdk.SELECTION_CLIPBOARD)
        paths = []
        if clipboard.wait_is_uris_available():
            paths = [GLib.filename_from_uri(uri)[0] for uri in clipboard.wait_for_uris() or []
                     if uri.startswith("file://")]
        if paths and self.insert_image_files(paths):
            view.stop_emission_by_name("paste-clipboard")
            return
        if clipboard.wait_is_image_available() and not clipboard.wait_is_text_available():
            pixbuf = clipboard.wait_for_image()
            if pixbuf is not None:
                try:
                    self.insert_image(images.save_pixbuf(pixbuf, self.images_dir))
                except (OSError, GLib.Error):
                    return
                view.stop_emission_by_name("paste-clipboard")

    def _on_drag_received(self, view, context, x, y, data, _info, time):
        uris = data.get_uris() or []
        paths = [GLib.filename_from_uri(uri)[0] for uri in uris if uri.startswith("file://")]
        if not paths:
            return
        bx, by = view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, x, y)
        found = view.get_iter_at_location(bx, by)
        where = found[1] if isinstance(found, tuple) else found
        if self.insert_image_files(paths, where):
            view.stop_emission_by_name("drag-data-received")
            Gtk.drag_finish(context, True, False, time)

    def choose_image(self):
        dialog = Gtk.FileChooserNative.new(_("Вставить картинку"), self, Gtk.FileChooserAction.OPEN,
                                           _("Вставить"), _("Отмена"))
        dialog.set_select_multiple(True)
        image_filter = Gtk.FileFilter()
        image_filter.set_name(_("Картинки"))
        image_filter.add_pixbuf_formats()
        dialog.add_filter(image_filter)
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            self.insert_image_files([f.get_path() for f in dialog.get_files() if f.get_path()])
        dialog.destroy()

    def _image_at(self, x, y):
        """Имя картинки под точкой (x, y) окна текста или None."""
        bx, by = self.view.window_to_buffer_coords(Gtk.TextWindowType.TEXT, int(x), int(y))
        found = self.view.get_iter_at_location(bx, by)
        it = found[1] if isinstance(found, tuple) else found
        if it is None:
            return None
        candidate = it.copy()
        for _step in range(2):  # под курсором или сразу перед ним
            pixbuf = candidate.get_pixbuf()
            name = images.name_of(pixbuf)
            if name:
                rect = self.view.get_iter_location(candidate)
                if rect.x <= bx < rect.x + pixbuf.get_width() and rect.y <= by < rect.y + rect.height:
                    return name
            if not candidate.backward_char():
                break
        return None

    def open_image(self, name):
        viewer = images.ImageViewer(self.images_dir / name)
        viewer.show_all()
        return viewer

    # --- форматирование ---

    def _apply_saved_formats(self):
        buffer = self.view.get_buffer()
        length = buffer.get_char_count()
        for item in self.note.formats or []:
            try:
                start, end, name = item
            except (TypeError, ValueError):
                continue
            if (name in FORMAT_TAGS and isinstance(start, int) and isinstance(end, int)
                    and 0 <= start < end <= length):
                buffer.apply_tag_by_name(
                    name, buffer.get_iter_at_offset(start), buffer.get_iter_at_offset(end)
                )

    def collect_formats(self):
        """Диапазоны всех тегов форматирования: [[начало, конец, имя], ...]."""
        buffer = self.view.get_buffer()
        result = []
        for name in FORMAT_TAGS:
            tag = buffer.get_tag_table().lookup(name)
            it = buffer.get_start_iter()
            while True:
                if it.has_tag(tag):
                    begin = it.get_offset()
                    if not it.forward_to_tag_toggle(tag):
                        result.append([begin, buffer.get_char_count(), name])
                        break
                    result.append([begin, it.get_offset(), name])
                elif not it.forward_to_tag_toggle(tag):
                    break
        return sorted(result)

    def _on_tags_changed(self, _buffer, tag, *_rest):
        if not self._loading and tag.get_property("name") in FORMAT_TAGS:
            self._schedule_save()

    @staticmethod
    def _range_fully_tagged(tag, start, end):
        it = start.copy()
        while it.compare(end) < 0:
            if not it.has_tag(tag):
                return False
            it.forward_char()
        return True

    def format_state(self, name):
        """Включён ли формат: на всём выделении или в точке ввода."""
        buffer = self.view.get_buffer()
        tag = buffer.get_tag_table().lookup(name)
        if buffer.get_has_selection():
            return self._range_fully_tagged(tag, *buffer.get_selection_bounds())
        if name in self._typing:
            return self._typing[name]
        before = buffer.get_iter_at_mark(buffer.get_insert())
        return before.backward_char() and before.has_tag(tag)

    def toggle_format(self, name):
        buffer = self.view.get_buffer()
        tag = buffer.get_tag_table().lookup(name)
        if buffer.get_has_selection():
            start, end = buffer.get_selection_bounds()
            if self._range_fully_tagged(tag, start, end):
                buffer.remove_tag(tag, start, end)
            else:
                buffer.apply_tag(tag, start, end)
        else:
            # Без выделения формат действует на то, что пользователь напечатает дальше.
            self._typing[name] = not self.format_state(name)
            self._typing_pos = buffer.get_iter_at_mark(buffer.get_insert()).get_offset()
        self.view.grab_focus()

    def _on_insert_text(self, buffer, location, text, _length):
        if not self._typing or self._loading or self._busy:
            return
        end = location.get_offset()
        start = end - len(text)
        if start != self._typing_pos:
            self._typing.clear()  # курсор ушёл в другое место
            return
        begin_iter, end_iter = buffer.get_iter_at_offset(start), buffer.get_iter_at_offset(end)
        for name, enabled in self._typing.items():
            if enabled:
                buffer.apply_tag_by_name(name, begin_iter, end_iter)
            else:
                buffer.remove_tag_by_name(name, begin_iter, end_iter)
        self._typing_pos = end

    # --- поиск: подсветка найденного ---

    def highlight(self, query):
        """Подсветить все вхождения query и прокрутить к первому. Возвращает их число."""
        self._clear_highlight()
        query = (query or "").strip().lower()
        if not query:
            return 0
        buffer = self.view.get_buffer()
        text = self._text().lower()
        first, count, pos = None, 0, text.find(query)
        while pos != -1:
            start = buffer.get_iter_at_offset(pos)
            end = buffer.get_iter_at_offset(pos + len(query))
            buffer.apply_tag(self.found_tag, start, end)
            first = pos if first is None else first
            count += 1
            pos = text.find(query, pos + len(query))
        if first is not None:
            self.view.scroll_to_iter(buffer.get_iter_at_offset(first), 0.1, False, 0, 0)
        return count

    def _clear_highlight(self):
        buffer = self.view.get_buffer()
        buffer.remove_tag(self.found_tag, *buffer.get_bounds())

    # --- чекбоксы ---

    @staticmethod
    def _line_bounds(iter_):
        start = iter_.copy()
        start.set_line_offset(0)
        end = start.copy()
        if not end.ends_line():
            end.forward_to_line_end()
        return start, end

    def _replace_prefix(self, start, old_len, new_prefix):
        """Заменить первые old_len символов строки; курсор остаётся на месте."""
        buffer = self.view.get_buffer()
        cursor = buffer.get_iter_at_mark(buffer.get_insert()).get_offset()
        line_start = start.get_offset()
        self._busy = True
        try:
            if old_len:
                end = start.copy()
                end.forward_chars(old_len)
                buffer.delete(start, end)
            if new_prefix:
                buffer.insert(buffer.get_iter_at_offset(line_start), new_prefix)
        finally:
            self._busy = False
        if cursor > line_start:
            cursor = max(line_start, cursor + len(new_prefix) - old_len)
        buffer.place_cursor(buffer.get_iter_at_offset(cursor))

    def _convert_prefix(self):
        """Набранное «[ ] » на текущей строке превращается в ☐, а «- » — в длинное тире."""
        if self._destroyed:
            return False
        buffer = self.view.get_buffer()
        start, end = self._line_bounds(buffer.get_iter_at_mark(buffer.get_insert()))
        line = buffer.get_text(start, end, False)
        converted = checklist.converted(line)
        if converted != line:
            self._replace_prefix(start, 4, converted[:2])
            return False
        # Автозамена «- » на длинное тире включается в настройках: по умолчанию дефис остаётся
        # дефисом, а список делает «-» и Tab.
        if self.app.settings["dash_autoconvert"] and checklist.dash_converted(line) != line:
            marker = start.copy()
            marker.forward_chars(len(line) - len(line.lstrip(" ")))
            self._replace_prefix(marker, 2, checklist.DASH)
        return False

    def toggle_checklist(self):
        """Добавить чекбокс к выделенным строкам или убрать, если он уже везде."""
        buffer = self.view.get_buffer()
        if buffer.get_has_selection():
            first, last = buffer.get_selection_bounds()
            lines = range(first.get_line(), last.get_line() + 1)
        else:
            line = buffer.get_iter_at_mark(buffer.get_insert()).get_line()
            lines = range(line, line + 1)
        texts = [
            buffer.get_text(*self._line_bounds(buffer.get_iter_at_line(n)), False)
            for n in lines
        ]
        all_items = all(checklist.is_item(t) for t in texts)
        # С конца, чтобы смещения предыдущих строк не менялись.
        for n, text in reversed(list(zip(lines, texts))):
            start = buffer.get_iter_at_line(n)
            if all_items:
                self._replace_prefix(start, 2, "")
            elif not checklist.is_item(text):
                self._replace_prefix(start, 0, checklist.OFF)
        self.view.grab_focus()

    def _on_key_press(self, _widget, event):
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        shift = event.state & Gdk.ModifierType.SHIFT_MASK
        if ctrl:
            if is_key(event, Gdk.KEY_a):
                buffer = self.view.get_buffer()
                buffer.select_range(buffer.get_start_iter(), buffer.get_end_iter())
                return True
            if is_key(event, Gdk.KEY_l):
                self.toggle_checklist()
                return True
            if is_key(event, Gdk.KEY_b):
                self.toggle_format("bold")
                return True
            if is_key(event, Gdk.KEY_i):
                self.toggle_format("italic")
                return True
            if is_key(event, Gdk.KEY_u):
                self.toggle_format("underline")
                return True
            if shift and is_key(event, Gdk.KEY_x):
                self.toggle_format("strike")
                return True
            if event.keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
                self.change_font(+1)
                return True
            if event.keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract, Gdk.KEY_underscore):
                self.change_font(-1)
                return True
            if event.keyval in (Gdk.KEY_0, Gdk.KEY_KP_0):
                self.change_font(0)
                return True
        if not ctrl:
            if event.keyval in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab) and self._on_tab(
                back=bool(shift) or event.keyval == Gdk.KEY_ISO_Left_Tab
            ):
                return True
            if event.keyval == Gdk.KEY_BackSpace and not shift and self._on_backspace():
                return True
        plain_enter = event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not (ctrl or shift)
        if not plain_enter:
            return False
        buffer = self.view.get_buffer()
        cursor = buffer.get_iter_at_mark(buffer.get_insert())
        start, end = self._line_bounds(cursor)
        line = buffer.get_text(start, end, False)
        offset = cursor.get_line_offset()
        follow = checklist.on_enter(line)
        if follow is not None and offset >= len(checklist.OFF):
            if follow == "":  # Enter на пустом пункте завершает список
                self._replace_prefix(start, len(line), "")
            else:
                buffer.insert_at_cursor("\n" + follow)
                self.view.scroll_mark_onscreen(buffer.get_insert())
            return True
        action = checklist.dash_enter(line)
        if action is not None and offset >= checklist.dash_indent(line) + len(checklist.DASH):
            kind, prefix = action
            if kind == "continue":
                buffer.insert_at_cursor("\n" + prefix)
                self.view.scroll_mark_onscreen(buffer.get_insert())
            else:  # "outdent" или "end": пустой пункт выносится выше или список заканчивается
                self._replace_prefix(start, len(line), prefix)
            return True
        return False

    def _on_tab(self, back):
        """Tab вкладывает пункт списка с тире глубже, Shift+Tab выносит; «-» + Tab делает пункт."""
        buffer = self.view.get_buffer()
        marks = None
        if buffer.get_has_selection():
            first, last = buffer.get_selection_bounds()
            lines = list(range(first.get_line(), last.get_line() + 1))
            # Выделение запоминаем метками: правки строк его сбрасывают.
            marks = (buffer.create_mark(None, first, True), buffer.create_mark(None, last, False))
        else:
            lines = [buffer.get_iter_at_mark(buffer.get_insert()).get_line()]
        changed = False
        for n in reversed(lines):  # с конца: смещения предыдущих строк не меняются
            start = buffer.get_iter_at_line(n)
            line_offset = start.get_offset()  # итератор после правки недействителен
            line = buffer.get_text(*self._line_bounds(start), False)
            if back:
                cut = len(line) - len(checklist.outdented(line))
                if cut:
                    self._replace_prefix(start, cut, "")
                    changed = True
            elif checklist.indented(line) != line:
                cursor = buffer.get_iter_at_mark(buffer.get_insert()).get_offset()
                self._replace_prefix(start, 0, checklist.INDENT)
                if cursor == line_offset:  # курсор был в начале строки: остаётся у текста
                    buffer.place_cursor(buffer.get_iter_at_offset(cursor + len(checklist.INDENT)))
                changed = True
        if marks:
            buffer.select_range(buffer.get_iter_at_mark(marks[0]), buffer.get_iter_at_mark(marks[1]))
            for mark in marks:
                buffer.delete_mark(mark)
            return changed
        if changed or back or len(lines) != 1:
            return changed
        cursor = buffer.get_iter_at_mark(buffer.get_insert())
        start, end = self._line_bounds(cursor)
        line = buffer.get_text(start, end, False)
        match = re.fullmatch(r"( *)- ?", line)
        if match and cursor.equal(end):  # «-» или «- » и Tab превращают строку в пункт списка
            marker = start.copy()
            marker.forward_chars(len(match.group(1)))
            self._replace_prefix(marker, len(line) - len(match.group(1)), checklist.DASH)
            return True
        return False

    def _on_backspace(self):
        """Backspace сразу за маркером убирает его (как в Word), оставляя текст."""
        buffer = self.view.get_buffer()
        if buffer.get_has_selection():
            return False
        cursor = buffer.get_iter_at_mark(buffer.get_insert())
        start, end = self._line_bounds(cursor)
        line = buffer.get_text(start, end, False)
        indent = checklist.dash_indent(line)
        if indent is None or cursor.get_line_offset() != indent + len(checklist.DASH):
            return False
        marker = start.copy()
        marker.forward_chars(indent)
        self._replace_prefix(marker, len(checklist.DASH), "")
        return True

    def _on_scroll(self, _widget, event):
        """Ctrl + колесо мыши меняет размер шрифта."""
        if not event.state & Gdk.ModifierType.CONTROL_MASK:
            return False
        if event.direction == Gdk.ScrollDirection.UP:
            self.change_font(+1)
        elif event.direction == Gdk.ScrollDirection.DOWN:
            self.change_font(-1)
        elif event.direction == Gdk.ScrollDirection.SMOOTH and event.delta_y:
            self.change_font(-1 if event.delta_y > 0 else +1)
        return True

    def _checkbox_at(self, x, y):
        """Начало строки с чекбоксом, если точка (x, y) окна текста попала на квадратик."""
        buffer = self.view.get_buffer()
        bx, by = self.view.window_to_buffer_coords(Gtk.TextWindowType.TEXT, int(x), int(y))
        found = self.view.get_iter_at_location(bx, by)
        if isinstance(found, tuple):  # (есть ли текст под курсором, позиция)
            found, it = found
            if not found:
                return None
        else:
            it = found
        if it is None:
            return None
        start, end = self._line_bounds(it)
        if not checklist.is_item(buffer.get_text(start, end, False)):
            return None
        after = start.copy()
        after.forward_char()
        if self.view.get_iter_location(start).x <= bx < self.view.get_iter_location(after).x:
            return start
        return None

    def _on_view_press(self, _widget, event):
        """Клик по квадратику ☐/☑ переключает галочку, двойной по картинке открывает её."""
        if event.button == 1 and event.type == Gdk.EventType.DOUBLE_BUTTON_PRESS:
            name = self._image_at(event.x, event.y)
            if name:
                self.open_image(name)
                return True
        if event.button != 1 or event.type != Gdk.EventType.BUTTON_PRESS:
            return False
        start = self._checkbox_at(event.x, event.y)
        if start is None:
            return False
        buffer = self.view.get_buffer()
        line = buffer.get_text(*self._line_bounds(start), False)
        self._replace_prefix(start, 2, checklist.toggled(line)[:2])
        return True

    def _on_view_motion(self, _widget, event):
        """Над квадратиком чекбокса курсор обычная стрелка, над остальным текстом — «текст»."""
        text_window = self.view.get_window(Gtk.TextWindowType.TEXT)
        if text_window is not None:
            over_box = self._checkbox_at(event.x, event.y) is not None
            text_window.set_cursor(self._cursor("default" if over_box else "text"))
        return False

    def _prefix_width(self, prefix):
        """Ширина начала строки (отступ и маркер) в пикселях при текущем шрифте."""
        layout = self.view.create_pango_layout(prefix + "x")
        full = layout.get_pixel_size()[0]
        layout.set_text("x", -1)
        return full - layout.get_pixel_size()[0]

    def _refresh_list_style(self):
        """Перенесённые строки пункта выравниваются под текстом, а не под маркером."""
        if self._destroyed:
            return False
        buffer = self.view.get_buffer()
        begin, finish = buffer.get_bounds()
        for name in self._hang_tags:
            buffer.remove_tag_by_name(name, begin, finish)
        text = self.note.text
        if not any(mark.strip() in text for mark in (checklist.DASH, checklist.OFF, checklist.ON)):
            return False
        widths = {}
        it = buffer.get_start_iter()
        while True:
            start, end = self._line_bounds(it)
            line = buffer.get_text(start, end, False)
            indent = checklist.dash_indent(line)
            if indent is not None:
                prefix = line[: indent + len(checklist.DASH)]
            else:
                prefix = line[:2] if checklist.is_item(line) else None
            if prefix:
                width = widths.setdefault(prefix, self._prefix_width(prefix))
                name = f"hang{width}"
                if buffer.get_tag_table().lookup(name) is None:
                    buffer.create_tag(name, indent=-width)
                self._hang_tags.add(name)
                buffer.apply_tag_by_name(name, start, end)
            if not it.forward_line():
                break
        return False

    def _refresh_done_style(self):
        """Выполненные пункты зачёркиваются и бледнеют."""
        buffer = self.view.get_buffer()
        begin, finish = buffer.get_bounds()
        buffer.remove_tag(self.done_tag, begin, finish)
        if checklist.ON.strip() not in self.note.text:
            return
        it = buffer.get_start_iter()
        while True:
            start, end = self._line_bounds(it)
            if checklist.is_done(buffer.get_text(start, end, False)):
                text_start = start.copy()
                text_start.forward_chars(2)
                buffer.apply_tag(self.done_tag, text_start, end)
            if not it.forward_line():
                break

    # --- обновление из данных (синхронизация, восстановление) ---

    def refresh_from_note(self):
        """Подтянуть показанное в окне из self.note после внешнего изменения."""
        self._loading = True
        try:
            buffer = self.view.get_buffer()
            if self._text() != self.note.text:
                cursor = buffer.get_iter_at_mark(buffer.get_insert()).get_offset()
                buffer.set_text(self.note.text)
                self._apply_saved_images()
                buffer.place_cursor(buffer.get_iter_at_offset(min(cursor, buffer.get_char_count())))
            for name in FORMAT_TAGS:
                buffer.remove_tag_by_name(name, *buffer.get_bounds())
            self._apply_saved_formats()
        finally:
            self._loading = False
        self._apply_color()
        self._apply_font()
        self._update_placeholder()
        self._update_title_label()
        self._refresh_done_style()
        self._refresh_list_style()
        self.set_opacity(self._valid_opacity())

    # --- сохранение ---

    def _schedule_save(self, touch=True):
        """Отложенная запись. touch=False — правка не меняет «изменено»."""
        if self._loading:
            return
        if touch:
            self.store.touch(self.note)
        if self._save_source is not None:
            GLib.source_remove(self._save_source)
        self._save_source = GLib.timeout_add(SAVE_DELAY_MS, self._save_now)

    def _save_now(self):
        self._save_source = None
        self.note.formats = self.collect_formats()
        self.note.images = self.collect_images()
        self.store.save()
        return False

    def flush(self):
        """Сохранить немедленно, если есть отложенная запись."""
        if self._save_source is not None:
            GLib.source_remove(self._save_source)
            self._save_source = None
        self.note.formats = self.collect_formats()
        self.note.images = self.collect_images()
        self.store.save()
