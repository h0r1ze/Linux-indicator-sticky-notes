import os

# Тесты проверяют русский интерфейс; английский включается в них явно (tests/test_i18n.py).
os.environ["LC_ALL"] = "ru_RU.UTF-8"
