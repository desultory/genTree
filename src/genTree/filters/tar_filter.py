from pathlib import Path
from tarfile import TarInfo, data_filter

from .filters import PathFilters


def get_relative_prefix(path):
    """Takes a path, returns ../ for each path component"""
    path = Path(path).parent
    return Path("/".join([".." for _ in path.parts]))


def get_whiteout(member):
    old_path = Path(member.name)
    return TarInfo(name=str(old_path.with_name(f".wh.{old_path.name}")))


class WhiteoutError(Exception):
    def __init__(self, member):
        self.member = member
        super().__init__(f"Whiteout detected: {member}")

    @property
    def whiteout(self):
        return get_whiteout(self.member)


class OpaqueWhiteoutError(Exception):
    def __init__(self, member):
        self.member = member
        super().__init__(f"Opaque whiteout detected: {member}")

    @property
    def opaque(self):
        return TarInfo(name=str(Path(self.member.name).parent / ".wh..wh..opq"))


class GenTreeTarFilter(PathFilters):
    FILTERS = ["whiteout", "dev"]

    def __call__(self, member, *args, **kwargs):
        member = self.rewrite_absolute_symlinks(member)
        member = self.filter(member)
        if member is None:
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
            return self.logger.debug("Filtered device file: %s", member)
        return member

    def rewrite_absolute_symlinks(self, member):
        """Rewrites absolute symlinks to relative symlinks"""
        if member.issym() and member.linkname.startswith("/"):
            symlink_target = Path(member.linkname)
            relative_prefix = get_relative_prefix(member.path)
            self.logger.debug("Rewriting absolute symlink: %s -> %s" % (member.path, symlink_target))
            new_target = relative_prefix / symlink_target.relative_to("/")
            self.logger.debug("Rewrote absolute symlink: %s", new_target)
            member.linkname = str(new_target)
        return member
