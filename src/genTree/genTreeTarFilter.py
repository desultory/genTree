from zenlib.logging import loggify
from tarfile import data_filter
from pathlib import Path


def get_relative_prefix(path):
    """ Takes a path, returns ../ for each path component """
    path = Path(path).parent
    return Path("/".join([".." for _ in path.parts]))


class AbsoluteSymlinkFilterMixIn:
    def rewrite_absolute_symlinks(self, member):
        if member.issym() and member.linkname.startswith("/"):
            symlink_target = Path(member.linkname)
            relative_prefix = get_relative_prefix(member.path)
            self.logger.debug("Rewriting absolute symlink: %s -> %s" % (member.path, symlink_target))
            new_target = relative_prefix / symlink_target.relative_to("/")
            self.logger.debug("Rewrote absolute symlink: %s", new_target)
            member.linkname = str(new_target)
        return member


class DeviceFilterMixIn:
    def filter_devices(self, member):
        if member.ischr() or member.isblk():
            self.logger.debug("Filtering out device file: %s", member.name)
            return None
        return member

@loggify
class GenTreeTarFilter(AbsoluteSymlinkFilterMixIn, DeviceFilterMixIn):
    def __call__(self, member, *args, **kwargs):
        member = self.filter_devices(member)
        if member is None:
            return
        member = self.rewrite_absolute_symlinks(member)
        if args:
            member = data_filter(member, *args, **kwargs)
        return member

