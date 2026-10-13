"""Перевод интерфейса: русский (исходный язык строк в коде) и английский.

Строки в коде написаны по-русски и обёрнуты в _(); английские варианты лежат в
translations_en.py. Выбор языка: настройка «language» (system | ru | en); «system»
берёт язык из переменных окружения LC_ALL, LC_MESSAGES, LANGUAGE, LANG.
Язык применяется при запуске, поэтому константы модулей хранят «сырые» строки
(их помечают N_()), а переводятся они там, где показываются.
"""
import os

LANGUAGES = ("system", "ru", "en")
NATIVE_NAMES = {"ru": "Русский", "en": "English"}

_current = "ru"


def system_language() -> str:
    """ru, если локаль системы русская, иначе en."""
    for var in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
        value = os.environ.get(var, "")
        if value:
            # LANGUAGE может быть списком: ru:en
            first = value.split(":")[0].lower()
            if first in ("c", "posix"):
                continue
            return "ru" if first.startswith("ru") else "en"
    return "en"


def resolve(setting: str) -> str:
    if setting in ("ru", "en"):
        return setting
    return system_language()


def set_language(setting: str) -> str:
    """Применить настройку языка; возвращает действующий язык (ru или en)."""
    global _current
    _current = resolve(setting)
    return _current


def current() -> str:
    return _current


def N_(text):
    """Пометка строки для перевода без немедленного перевода (константы модулей)."""
    return text


def _(text):
    if _current == "en":
        from .translations_en import EN
        return EN.get(text, text)
    return text


def plural(count, ru_forms, en_forms):
    """Форма слова по числу. ru_forms: (1 заметка, 2 заметки, 5 заметок), en_forms: (one, many)."""
    n = abs(int(count))
    if _current == "en":
        return en_forms[0] if n == 1 else en_forms[1]
    if n % 10 == 1 and n % 100 != 11:
        return ru_forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return ru_forms[1]
    return ru_forms[2]
