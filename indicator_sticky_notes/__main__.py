import os
import sys

from . import legacy
from .app import StickyApp


def main():
    legacy.migrate()
    app = StickyApp()
    status = app.run(sys.argv)
    if app.restart_requested:  # смена языка: новый процесс читает настройки заново
        os.execv(sys.executable, [sys.executable, "-m", "indicator_sticky_notes"])
    return status


if __name__ == "__main__":
    sys.exit(main())
