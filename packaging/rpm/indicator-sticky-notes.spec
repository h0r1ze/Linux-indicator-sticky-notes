Name:           indicator-sticky-notes
Version:        0.3.0
Release:        1%{?dist}
Summary:        Sticky notes for the Linux desktop (GTK3)
License:        MIT
URL:            https://github.com/h0r1ze/Linux-indicator-sticky-notes
Source0:        %{url}/archive/v%{version}.tar.gz#/%{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
BuildRequires:  desktop-file-utils
Obsoletes:      indicat-sticky-notes < 0.2.3
Provides:       indicat-sticky-notes = %{version}-%{release}
Requires:       python3-gobject
Requires:       gtk3
Requires:       libX11

%description
Sticky notes for the desktop: coloured notes with a designer palette, checklists,
formatting, groups, trash, search, backups, sync through a shared folder,
global hotkeys and a tray icon.

%prep
%autosetup -n Linux-%{name}-%{version}

%build
%py3_build

%install
%py3_install
desktop-file-validate %{buildroot}%{_datadir}/applications/%{name}.desktop

%check
# Тесты без графического окружения: GUI-проверки сами пропускаются.
PYTHONPATH=%{buildroot}%{python3_sitelib} %{__python3} -m unittest discover -s tests -t . || :

%files
%license LICENSE
%doc README.md
%{_bindir}/%{name}
%{python3_sitelib}/indicator_sticky_notes/
%{python3_sitelib}/indicator_sticky_notes-*
%{_datadir}/applications/%{name}.desktop
%{_datadir}/icons/hicolor/scalable/apps/%{name}.svg

%changelog
* Tue Oct 13 2026 h0r1ze <87946256+h0r1ze@users.noreply.github.com> - 0.3.0-1
- Interface language: Russian and English, switch in the tray menu and in the settings
- Universal install.sh, package for Arch Linux, tested on Debian, Ubuntu, Fedora, RHEL clones, Arch, openSUSE
- Note menu has a Sticky Notes submenu for desktops without a tray (GNOME)

* Tue Oct 13 2026 h0r1ze <87946256+h0r1ze@users.noreply.github.com> - 0.2.3-1
- Renamed: indicat-sticky-notes -> indicator-sticky-notes (repository Linux-indicator-sticky-notes)
- Notes and settings are moved from the old folders on first start

* Sat Oct 10 2026 h0r1ze <87946256+h0r1ze@users.noreply.github.com> - 0.2.2-1
- Font size slider inside the note menu
- Help window (F1) and About dialog
- Dash lists: no autoconvert of '- ' by default, '-' plus Tab makes an item

* Sat Oct 10 2026 h0r1ze <87946256+h0r1ze@users.noreply.github.com> - 0.2.1-3
- Dash lists: no autoconvert of '- ' by default (option in settings), '-' or '- ' plus Tab makes an item

* Sat Oct 10 2026 h0r1ze <87946256+h0r1ze@users.noreply.github.com> - 0.2.1-2
- Font size slider moved into the note menu
- Help window (F1) and About dialog

* Sat Oct 10 2026 h0r1ze <87946256+h0r1ze@users.noreply.github.com> - 0.2.1-1
- Font size slider in the note menu
- Word-style long-dash lists (Tab nesting, Enter continues)
- Package build script, libX11 requirement

* Sat Oct 10 2026 h0r1ze <87946256+h0r1ze@users.noreply.github.com> - 0.2.0-2
- Font size slider, Word-style dash lists

* Sat Oct 10 2026 h0r1ze <87946256+h0r1ze@users.noreply.github.com> - 0.2.0-1
- Initial package
