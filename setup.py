# Все метаданные здесь, а не в pyproject.toml: старые setuptools (RHEL 9 и клоны, Debian 11,
# Ubuntu 20.04) не читают секцию [project] и собирали бы пустой пакет.
import re
from pathlib import Path

from setuptools import setup

here = Path(__file__).resolve().parent
version = re.search(r'__version__ = "([^"]+)"',
                    (here / "indicator_sticky_notes" / "__init__.py").read_text(encoding="utf-8")).group(1)

setup(
    name="indicator-sticky-notes",
    version=version,
    description="Sticky notes for the Linux desktop (Python and GTK3) with a tray icon",
    long_description=(here / "README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    url="https://github.com/h0r1ze/Linux-indicator-sticky-notes",
    author="h0r1ze",
    license="MIT",
    python_requires=">=3.9",
    keywords="sticky notes gtk desktop",
    classifiers=[
        "Environment :: X11 Applications :: GTK",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
    ],
    # PyGObject и GTK3 ставятся системным пакетным менеджером, а не из PyPI.
    packages=["indicator_sticky_notes"],
    scripts=["bin/indicator-sticky-notes"],
    data_files=[
        ("share/applications", ["data/indicator-sticky-notes.desktop"]),
        ("share/icons/hicolor/scalable/apps", ["data/icons/hicolor/scalable/apps/indicator-sticky-notes.svg"]),
    ],
)
