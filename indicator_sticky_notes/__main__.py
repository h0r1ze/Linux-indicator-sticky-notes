import sys

from . import legacy
from .app import StickyApp


def main():
    legacy.migrate()
    return StickyApp().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
