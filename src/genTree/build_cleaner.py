from pathlib import Path
from shutil import rmtree

from .gen_tree_filters import PathFilters


class BuildCleaner(PathFilters):
    def clean(self, target_dir: Path):
        for f in target_dir.rglob("*"):
            check_f = f.relative_to(target_dir)
            if not self.filter(check_f):
                if f.is_dir():
                    self.logger.debug("Removing directory: %s", f)
                    rmtree(f)
                else:
                    self.logger.debug("Removing: %s", f)
                    f.unlink()
