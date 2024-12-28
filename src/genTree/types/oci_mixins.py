from shutil import rmtree

from zenlib.util import colorize


class OCIMixins:
    def apply_opaques(self, lower_root, opaques):
        """Applies opaques to the lower root, clearing all contents of the specified directories"""
        for opaque in opaques:
            opaque_path = lower_root / opaque
            if not opaque_path.exists():
                self.logger.warning("Opaque target not found: %s", colorize(opaque_path, "red"))
                continue

            for file in opaque_path.rglob("*"):
                if file.is_dir():
                    self.logger.debug("Opaquing directory: %s", file)
                    rmtree(file)
                else:
                    self.logger.debug("Opaquing file: %s", file)
                    file.unlink()

    def apply_whiteouts(self, lower_root, whiteouts):
        """Applies whiteouts to the lower root"""
        for whiteout in whiteouts:
            whiteout_path = lower_root / whiteout
            if whiteout_path.exists(follow_symlinks=False):
                if whiteout_path.is_dir():
                    self.logger.debug("Whiting out directory: %s", whiteout_path)
                    rmtree(whiteout_path)
                else:
                    self.logger.debug("Whiting out file: %s", whiteout_path)
                    whiteout_path.unlink()
            elif str(whiteout_path.parent.relative_to(lower_root)) in whiteouts:
                self.logger.debug("Parent of whiteout already whiteout: %s", whiteout_path.parent)
            else:
                self.logger.warning("Whiteout target not found: %s", colorize(whiteout_path, "red"))
