from pathlib import Path
from subprocess import run



from zenlib.util import colorize


class MountMixins:
    def mount_root_overlay(self, config):
        """Mounts an overlayfs for the build root"""
        self.logger.info(
            "[%s] Mounting overlayfs on: %s",
            colorize(config.name, "blue"),
            colorize(config.overlay_root, "cyan"),
        )
        run(
            [
                "mount",
                "-t",
                "overlay",
                "overlay",
                "-o",
                f"userxattr,lowerdir={config.lower_root},upperdir={config.upper_root},workdir={config.work_root}",
                config.overlay_root,
            ],
            check=True,
        )

    def mount_seed_overlay(self):
        """Mounts an overlayfs on the seed root"""
        if not self.config.seed_root.exists():
            raise FileNotFoundError(f"Seed root not found: {self.config.seed_root}")
        self.config.check_dir(["upper_seed_root", "work_seed_root", "sysroot"])
        self.logger.info("Mounting overlayfs on: %s", colorize(self.config.sysroot, "cyan", bold=True))
        run(
            [
                "mount",
                "-t",
                "overlay",
                "overlay",
                "-o",
                f"userxattr,lowerdir={self.config.seed_root},upperdir={self.config.upper_seed_root},workdir={self.config.work_seed_root}",
                self.config.sysroot,
            ],
            check=True,
        )

    def bind_mount(self, source: Path, dest: Path, recursive=False, readonly=True, file=False):
        """Bind mounts a source directory over a destination directory"""
        source, dest = Path(source), Path(dest)
        mount_type = "--rbind" if recursive else "--bind"
        if dest.is_mount():
            self.logger.info(
                "Unmounting %s: %s", colorize(source, "red"), colorize(dest, "magenta")
            )
            run(["umount", dest], check=True)

        if not source.exists():
            if file:
                self.logger.debug("Creating mount source file: %s", source)
                source.touch()
            else:
                self.logger.debug("Creating mount source directory: %s", source)
                source.mkdir(parents=True)

        if not dest.exists():
            if file:
                self.logger.debug("Creating mount destination file: %s", dest)
                dest.touch()
            else:
                self.logger.debug("Creating mount destination directory: %s", dest)
                dest.mkdir(parents=True)

        args = ["mount", mount_type, source, dest]
        if readonly:
            args.extend(["-o", "ro"])


        self.logger.info(
            "Mounting %s over: %s", colorize(source, "green"), colorize(dest, "magenta", bold=True)
        )
        run(args, check=True)

    def mount_system_dirs(self):
        """Mounts /proc, /sys, and /dev in the build root"""
        config = self.config
        self.logger.info(
            "[%s] Mounting system directories in: %s",
            colorize(config.name, "blue"),
            colorize(config.sysroot, "cyan", bold=True),
        )
        self.bind_mount("/proc", config.sysroot / "proc", recursive=True)
        self.bind_mount("/sys", config.sysroot / "sys", recursive=True)
        self.bind_mount("/dev", config.sysroot / "dev", recursive=True)
        self.bind_mount("/run", config.sysroot / "run", recursive=True)
        run(["mount", "--types", "devpts", "devpts", config.sysroot / "dev/pts"], check=True)
