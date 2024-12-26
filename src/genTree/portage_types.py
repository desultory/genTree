from collections import UserDict


class FlagBool:
    """A boolean that represents as 'y' or 'n'"""

    def __init__(self, value):
        self.value = bool(value)

    def __bool__(self):
        return self.value

    def __call__(self):
        return self.value

    def __str__(self):
        return "y" if self else "n"


class EmergeBools(UserDict):
    """Dict of FlagBool objects"""

    def __init__(self, flags):
        super().__init__()
        self.update(flags)

    def __setitem__(self, key, value):
        super().__setitem__(key, FlagBool(value))

    def __getitem__(self, key):
        from . import PORTAGE_PLAIN_BOOLS

        if key in PORTAGE_PLAIN_BOOLS:
            if super().__getitem__(key):
                return f"--{key}"
            return

        bool_str = f"--{key.replace('_', '-')}={super().__getitem__(key)}"
        return bool_str

    def __str__(self):
        return " ".join((value for value in self.values() if value))


class PortageFlags(set):
    def __init__(self, flags):
        """Splits the flags by whitespace and adds them to the set"""
        if isinstance(flags, str):
            super().__init__(flags.split())
        else:
            super().__init__(flags)

    def add(self, item):
        """If it starts with +, remove that prefix and add the item.
        Remove - variants if they exist.

        If it starts with -, add the item keeping the prefix.
        Remove standard variants if they exist.
        """
        if item.startswith("+"):
            item = item[1:]
            if f"-{item}" in self:  # Remove negative variant if it exists
                self.remove(f"-{item}")

        if item.startswith("-"):
            san_item = item[1:]
            if san_item in self:  # Remove positive variant if it exists
                self.remove(san_item)

        super().add(item)

    def remove(self, item):
        """If it starts with +, remove that prefix and remove the item
        If it starts with -, attmpt to remove it but trys stripping the prefix if it fails."""
        if item.startswith("-"):
            try:
                super().remove(item)
            except KeyError:
                super().remove(item[1:])
            return

        if item.startswith("+"):
            item = item[1:]

        super().remove(item)

    def __or__(self, other):
        for item in other:
            self.add(item)
        return self

    def __str__(self):
        return " ".join(self)
