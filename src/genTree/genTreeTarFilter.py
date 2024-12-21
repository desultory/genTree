from zenlib.logging import loggify
from tarfile import data_filter
from pathlib import Path


def get_relative_prefix(path):
    """ Takes a path, returns ../ for each path component """
    path = Path(path).parent
    return Path("/".join([".." for _ in path.parts]))


@loggify
class GenTreeTarFilter:
    def __init__(self, *args, **kwargs):
        for name in kwargs.copy():
            if name.startswith("filter_"):
                setattr(self, name, kwargs.pop(name))
        super().__init__(*args, **kwargs)

    @property
    def filters(self):
        for f in dir(self):
            if f.startswith("filter_"):
                filter_name = f.replace("filter_", "")
                if getattr(self, f"filter_{filter_name}"):
                    yield getattr(self, f"f_{filter_name}")


    def __call__(self, member, *args, **kwargs):
        member = self.rewrite_absolute_symlinks(member)
        for f in self.filters:
            if member := f(member):
                continue
            return

        if args:
            member = data_filter(member, *args, **kwargs)
        return member

    def f_dev(self, member):
        """ Filters device files """
        if member.ischr() or member.isblk():
            return self.logger.debug("Filtering device file: %s", member.name)
        return member

    def f_man(self, member):
        """ Filters manual pages """
        if member.name.startswith("usr/share/man/"):
            return self.logger.debug("Filtering man page: %s", member.name)
        return member

    def f_docs(self, member):
        """ Filters documentation """
        if member.name.startswith("usr/share/doc/"):
            return self.logger.debug("Filtering documentation: %s", member.name)
        return member

    def f_include(self, member):
        """ Filters include files """
        if member.name.startswith("usr/include/"):
            return self.logger.debug("Filtering include file: %s", member.name)
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

