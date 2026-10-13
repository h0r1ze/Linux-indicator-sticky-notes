"""Перенос данных из папок старой версии (пакет назывался indicat-sticky-notes)."""
import os
import shutil
from pathlib import Path

OLD = "indicat-sticky-notes"
NEW = "indicator-sticky-notes"


def _base(env, fallback):
    return Path(os.environ.get(env) or os.path.expanduser(fallback))


def _move_dir(old: Path, new: Path):
    if old.is_dir() and not new.exists():
        new.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old), str(new))


def migrate():
    """Заметки, настройки и записи автозапуска/меню: старые имена → новые. Безопасно вызывать при каждом запуске."""
    data = _base("XDG_DATA_HOME", "~/.local/share")
    config = _base("XDG_CONFIG_HOME", "~/.config")
    _move_dir(data / OLD, data / NEW)
    _move_dir(config / OLD, config / NEW)
    for folder in (config / "autostart", data / "applications"):
        old = folder / f"{OLD}.desktop"
        if not old.is_file():
            continue
        new = folder / f"{NEW}.desktop"
        if new.exists() or "Exec=" not in old.read_text(encoding="utf-8", errors="replace"):
            old.unlink()
            continue
        # Записи, созданные приложением, указывали на старое имя команды или модуля.
        text = old.read_text(encoding="utf-8")
        new.write_text(text.replace("indicat_sticky_notes", "indicator_sticky_notes")
                           .replace(OLD, NEW), encoding="utf-8")
        old.unlink()
