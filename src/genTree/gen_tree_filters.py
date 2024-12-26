from pathlib import Path
from tarfile import TarInfo

from zenlib.logging import loggify


class MergedFilter(type):
    def __new__(cls, name, bases, dct):
        base_filters = [f for b in bases for f in getattr(b, "FILTERS", [])]
        base_name_filters = [f for b in bases for f in getattr(b, "NAME_FILTERS", [])]
        dct["FILTERS"] = dct.get("FILTERS", []) + base_filters
        dct["NAME_FILTERS"] = dct.get("NAME_FILTERS", []) + base_name_filters
        return super().__new__(cls, name, bases, dct)


@loggify
class FilterClass(metaclass=MergedFilter):
    FILTERS = []

    def __init__(self, **kwargs):
        self.process_filter_args(kwargs)

    def process_filter_args(self, kwargs):
        for name in kwargs:
            if name in self.FILTERS:
                setattr(self, name, kwargs[name])
            else:
                self.logger.warning("Unknown filter: %s", name)

    @property
    def filters(self):
        for f in self.FILTERS:
            if getattr(self, f, None):
                yield getattr(self, f"f_{f}")

    def filter(self, target):
        """Runs all filters on the target in order"""
        orig_target = target
        for f in self.filters:
            if f.__name__.removeprefix("f_") in self.NAME_FILTERS:
                if isinstance(target, str):
                    val = f(target)
                elif isinstance(target, TarInfo):
                    val = f(target.name)
                elif isinstance(target, Path):
                    if target.is_absolute():
                        val = f(str(target.relative_to("/")))
                    else:
                        val = f(str(target))
                else:
                    val = f(str(target))
                if not val:
                    target = None
            else:
                target = f(target)
            if target is None:
                return self.logger.debug("[%s] Filter blocked: %s", f.__name__, orig_target)
            self.logger.log(5, "[%s] Filter passed: %s", f.__name__, target)
        return target


class PathFilters(FilterClass):
    DOC_DIRS = ["usr/share/doc/", "usr/share/gtk-doc/"]
    LOCALE_DIRS = ["usr/share/locale/", "usr/share/i18n/locales/", "usr/lib/gconv/", "usr/lib64/gconv/"]
    FILTERS = ["man", "docs", "include", "locales", "charmaps", "completions", "vardbpkg"]
    NAME_FILTERS = FILTERS

    def f_charmaps(self, name) -> bool:
        """Filters charmaps"""
        if name.startswith("usr/share/i18n/charmaps/"):
            return False
        return True

    def f_man(self, name) -> bool:
        """Filters manual pages"""
        if name.startswith("usr/share/man/"):
            return False
        return True

    def f_docs(self, name) -> bool:
        """Filters documentation"""
        if any(name.startswith(d) for d in self.DOC_DIRS):
            return False
        return True

    def f_include(self, name) -> bool:
        """Filters include files"""
        if name.startswith("usr/include/"):
            return False
        return True

    def f_locales(self, name) -> bool:
        """Filters locales"""
        if any(name.startswith(d) for d in self.LOCALE_DIRS):
            return False
        return True

    def f_completions(self, name) -> bool:
        """Filters shell completions"""
        if name.startswith("usr/share/bash-completion/"):
            return False
        return True

    def f_vardbpkg(self, name) -> bool:
        """Filters /var/db/pkg"""
        if name.startswith("var/db/pkg/"):
            return False
        return True
