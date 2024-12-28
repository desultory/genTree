from pathlib import Path
from tarfile import data_filter

from zenlib.logging import loggify


@loggify
class WhiteoutFilter:
    def __init__(self, *args, **kwargs):
        self.whiteouts = kwargs.pop("whiteouts", set())
        self.opaques = kwargs.pop("opaques", set())
        super().__init__(*args, **kwargs)

    def __call__(self, member, *args, **kwargs):
        if member := self.detect_opaque(member):
            if member := self.detect_whiteout(member):
                if args:
                    return data_filter(member, *args, **kwargs)
        return member

    def detect_opaque(self, member):
        """Detects an opaque file
        This is represented by an empty file named .wh..wh..opq
        Only returns the member if it is not an opaque.
        """
        member_path = Path(member.name)
        if member_path.name == ".wh..wh..opq" and member.size == 0 and member.isreg():
            self.logger.debug("Detected opaque: %s", member.name)
            self.opaques.add(str(member_path.parent))
            return None
        return member

    def detect_whiteout(self, member):
        """Detects a whiteout file
        This is represented by an empty file named .wh.<filename>
        Only returns the member if it is not a whiteout.
        """
        member_path = Path(member.name)
        if member_path.name.startswith(".wh.") and member.size == 0 and member.isreg():
            self.logger.debug("Detected whiteout: %s", member.name)
            self.whiteouts.add(str(member_path.with_name(member_path.name[4:])))
            return None
        return member
