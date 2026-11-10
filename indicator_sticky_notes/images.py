"""Картинки в заметках: файлы в папке images/ рядом с notes.json.

В тексте заметки картинка — символ IMAGE_CHAR (его же GtkTextBuffer.get_slice
возвращает на месте вставленного изображения), а note.images хранит пары
[смещение, имя файла]. Имя — хеш содержимого, поэтому одна и та же картинка
хранится один раз, а при синхронизации файлы не конфликтуют.
"""
import hashlib
import shutil
from pathlib import Path

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402

from .i18n import _  # noqa: E402
from .storage import IMAGE_CHAR  # noqa: E402

NAME_OPTION = "x-sticky-image"  # имя файла, привязанное к миниатюре в буфере
EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".tif", ".tiff")
THUMB_MAX = 220


def images_dir(notes_path) -> Path:
    return Path(notes_path).parent / "images"


def is_image_file(path) -> bool:
    return Path(path).suffix.lower() in EXTENSIONS and Path(path).is_file()


def _hashed_name(data: bytes, suffix: str) -> str:
    return hashlib.sha1(data).hexdigest()[:20] + suffix


def import_file(path, directory) -> str:
    """Скопировать картинку в папку заметок. Возвращает имя файла."""
    path = Path(path)
    data = path.read_bytes()
    name = _hashed_name(data, path.suffix.lower())
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    if not target.exists():
        shutil.copyfile(path, target)
    return name


def save_pixbuf(pixbuf, directory) -> str:
    """Картинку из буфера обмена сохранить как PNG. Возвращает имя файла."""
    ok, data = pixbuf.save_to_bufferv("png", [], [])
    if not ok:
        raise OSError("png")
    name = _hashed_name(bytes(data), ".png")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    if not target.exists():
        target.write_bytes(bytes(data))
    return name


def thumbnail(directory, name, max_width=THUMB_MAX, max_height=THUMB_MAX):
    """Уменьшенная картинка для вставки в текст; если файла нет — значок «нет картинки»."""
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(Path(directory) / name))
        width, height = pixbuf.get_width(), pixbuf.get_height()
        scale = min(1.0, max_width / width, max_height / height)
        if scale < 1.0:
            pixbuf = pixbuf.scale_simple(
                max(1, int(width * scale)), max(1, int(height * scale)),
                GdkPixbuf.InterpType.BILINEAR,
            )
        else:
            pixbuf = pixbuf.copy()  # своя копия, чтобы опция имени не досталась кешу
    except GLib.Error:
        theme = Gtk.IconTheme.get_default()
        try:
            pixbuf = theme.load_icon("image-missing", 48, 0).copy()
        except GLib.Error:
            pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 48, 48)
            pixbuf.fill(0x80808080)
    pixbuf.set_option(NAME_OPTION, name)
    return pixbuf


def name_of(pixbuf):
    return pixbuf.get_option(NAME_OPTION) if pixbuf is not None else None


def file_uri(directory, name) -> str:
    return (Path(directory) / name).resolve().as_uri()


def replace_chars(text, images, render):
    """Заменить символы картинок в text на render(имя) по порядку note.images."""
    names = [name for _offset, name in sorted(images, key=lambda item: item[0])]
    out, index = [], 0
    for char in text:
        if char == IMAGE_CHAR:
            out.append(render(names[index]) if index < len(names) else "")
            index += 1
        else:
            out.append(char)
    return "".join(out)


class ImageViewer(Gtk.Window):
    """Отдельное окно с картинкой в полный размер (уменьшается под экран)."""

    def __init__(self, path, parent=None):
        super().__init__(title=_("Картинка"))
        if parent is not None:
            self.set_transient_for(parent)
        self.set_position(Gtk.WindowPosition.CENTER_ON_PARENT if parent else Gtk.WindowPosition.CENTER)
        self.path = Path(path)
        image = Gtk.Image()
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(self.path))
            screen = Gdk.Screen.get_default()
            max_w = int(screen.get_width() * 0.8) if screen else 1200
            max_h = int(screen.get_height() * 0.8) if screen else 900
            width, height = pixbuf.get_width(), pixbuf.get_height()
            scale = min(1.0, max_w / width, max_h / height)
            if scale < 1.0:
                pixbuf = pixbuf.scale_simple(int(width * scale), int(height * scale),
                                             GdkPixbuf.InterpType.BILINEAR)
            image.set_from_pixbuf(pixbuf)
            self.set_default_size(pixbuf.get_width() + 24, pixbuf.get_height() + 24)
        except GLib.Error:
            image.set_from_icon_name("image-missing", Gtk.IconSize.DIALOG)
            self.set_default_size(320, 240)
        scroll = Gtk.ScrolledWindow()
        scroll.add(image)
        self.add(scroll)
        self.connect("key-press-event", self._on_key)

    def _on_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.destroy()
            return True
        return False
