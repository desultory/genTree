from pathlib import Path
from tarfile import TarInfo, data_filter

from zenlib.logging import loggify


def get_relative_prefix(path):
    """Takes a path, returns ../ for each path component"""
    path = Path(path).parent
    return Path("/".join([".." for _ in path.parts]))


class WhiteoutError(Exception):
    def __init__(self, member):
        self.member = member
        super().__init__(f"Whiteout detected: {member}")

    @property
    def whiteout(self):
        old_path = Path(self.member.name)
        return TarInfo(name=str(old_path.with_name(f".wh.{old_path.name}")))


class OpaqueWhiteoutError(Exception):
    def __init__(self, member):
        self.member = member
        super().__init__(f"Opaque whiteout detected: {member}")

    @property
    def parent_dir(self):
        """Returns a TarInfo object for the parent directory of the whiteout"""
        from tarfile import DIRTYPE

        return TarInfo(name=str(Path(self.member.name).parent), type=DIRTYPE)

    @property
    def opaque(self):
        return TarInfo(name=str(Path(self.member.name).parent / ".wh..wh..opq"))


@loggify
class GenTreeTarFilter:
    DOC_DIRS = ["usr/share/doc/", "usr/share/gtk-doc/"]
    LOCALE_DIRS = ["usr/share/locale/", "usr/share/i18n/locales/", "usr/lib/gconv/", "usr/lib64/gconv/"]
    FILTERS = ["whiteout", "dev", "man", "docs", "include", "locales", "charmaps", "completions", "vardbpkg"]

    def __init__(self, *args, **kwargs):
        for name in kwargs.copy():
            if name.startswith("filter_"):
                setattr(self, name, kwargs.pop(name))
        super().__init__(*args, **kwargs)

    @property
    def filters(self):
        for f in self.FILTERS:
            if getattr(self, f"filter_{f}", None):
                yield getattr(self, f"f_{f}")

    def __call__(self, member, *args, **kwargs):
        member = self.rewrite_absolute_symlinks(member)
        for f in self.filters:
            if member := f(member):
                continue
            return

        if args:
            member = data_filter(member, *args, **kwargs)
        return member

    def f_whiteout(self, member):
        """Detects whiteouts created by the overlay as character devices
        or empty files with the 'trusted.overlay.whiteout' xattr.

        Creates a new tar member which is an empty file prefixed with ".wh."
        """
        whiteout = False
        if member.ischr() and member.devmajor == 0 and member.devminor == 0:
            self.logger.debug("Detected chardev whiteout: %s", member.name)
            whiteout = True
        if member.size == 0 and member.pax_headers.get("trusted.overlay.whiteout"):
            self.logger.debug("Detected empty file whiteout: %s", member.name)
            whiteout = True
        if not whiteout:
            return member
        raise WhiteoutError(member)

    def f_dev(self, member):
        """Filters device files"""
        if member.ischr() or member.isblk():
            return self.logger.debug("Filtering device file: %s", member.name)
        return member

    def f_charmaps(self, member):
        """Filters charmaps"""
        if member.name.startswith("usr/share/i18n/charmaps/"):
            return self.logger.debug("Filtering charmap: %s", member.name)
        return member

    def f_man(self, member):
        """Filters manual pages"""
        if member.name.startswith("usr/share/man/"):
            return self.logger.debug("Filtering man page: %s", member.name)
        return member

    def f_docs(self, member):
        """Filters documentation"""
        if any(member.name.startswith(d) for d in self.DOC_DIRS):
            return self.logger.debug("Filtering documentation: %s", member.name)
        return member

    def f_include(self, member):
        """Filters include files"""
        if member.name.startswith("usr/include/"):
            return self.logger.debug("Filtering include file: %s", member.name)
        return member

    def f_locales(self, member):
        """Filters locales"""
        if any(member.name.startswith(d) for d in self.LOCALE_DIRS):
            return self.logger.debug("Filtering locale: %s", member.name)
        return member

    def f_completions(self, member):
        """Filters shell completions"""
        if member.name.startswith("usr/share/bash-completion/"):
            return self.logger.debug("Filtering bash completion: %s", member.name)
        return member

    def f_vardbpkg(self, member):
        """Filters /var/db/pkg"""
        if member.name.startswith("var/db/pkg/"):
            return self.logger.debug("Filtering /var/db/pkg: %s", member.name)
        return member

    def rewrite_absolute_symlinks(self, member):
        if member.issym() and member.linkname.startswith("/"):
            symlink_target = Path(member.linkname)
            relative_prefix = get_relative_prefix(member.path)
            self.logger.debug("Rewriting absolute symlink: %s -> %s" % (member.path, symlink_target))
            new_target = relative_prefix / symlink_target.relative_to("/")
            self.logger.debug("Rewrote absolute symlink: %s", new_target)
            member.linkname = str(new_target)
        return member
