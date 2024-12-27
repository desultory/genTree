from pathlib import Path
from subprocess import CalledProcessError, run

from zenlib.util import colorize


class MountMixins:
    def mount_root_overlay(self, config):
        """Mounts an overlayfs for the build root"""
        config.logger.info(
            " =^= [%s] Mounting build overlay on: %s",
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

    def mount_config_overlay(self, config):
        """Mounts a config overlay over /etc/portage"""
        if Path("/etc/portage").is_mount():
            config.logger.info(" -v- Unmounting config overlay on /etc/portage")
            try:
                run(["umount", "/etc/portage"], check=True, capture_output=True)
            except CalledProcessError as e:
                if e.returncode == 16:
                    config.logger.warning("Unable to update userspace mount table unmounting /etc/portage.")
                else:
                    raise e
        if not config.config_overlay:
            return config.logger.debug("No config overlay specified, skipping config overlay mount")
        config_dir = Path("/config") / config.config_overlay

        if not config_dir.exists():
            if config.config_overlay:
                raise FileNotFoundError(f"Config overlay directory not found: {config_dir}")
            return config.logger.debug("Config overlay directory not found: %s", config_dir)

        upper_config = Path("/config") / "upper_config"
        work_config = Path("/config") / "work_config"

        for d in [upper_config, work_config]:
            if not d.exists():
                config.logger.debug("Creating directory: %s", d)
                d.mkdir(parents=True)

        config.logger.info(
            " =-= [%s] Mounting config overlay on: %s", colorize(config.name, "green"), colorize(config_dir, "blue")
        )
        run(
            [
                "mount",
                "-t",
                "overlay",
                "overlay",
                "-o",
                f"userxattr,lowerdir={config_dir},upperdir={upper_config},workdir={work_config}",
                "/etc/portage",
            ],
            check=True,
        )

    def mount_seed_overlay(self):
        """Mounts an overlayfs on the seed root"""
        if not self.config.seed_root.exists():
            raise FileNotFoundError(f"Seed root not found: {self.config.seed_root}")
        self.config.check_dir(["upper_seed_root", "work_seed_root", "sysroot"])
        self.logger.info(" ~/* Mounting seed overlay on: %s", colorize(self.config.sysroot, "cyan", bold=True))
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
        if recursive:
            mount_type = "--rbind"
            s1 = "*"
        else:
            mount_type = "--bind"
            s1 = "+"
        if file:
            s1 = "."

        s2 = ">" if readonly else "-"

        if dest.is_mount():
            self.logger.info(" - - Unmounting %s: %s", colorize(source, "red"), colorize(dest, "magenta"))
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
            " %s%s%s Mounting %s over: %s", s1, s2, s1, colorize(source, "green"), colorize(dest, "magenta", bold=True)
        )
        run(args, check=True)

    def mount_system_dirs(self):
        """Mounts /proc, /sys, and /dev in the build root"""
        config = self.config
        self.logger.info(" *v* Mounting system directories in: %s", colorize(config.sysroot, "cyan", bold=True))
        self.bind_mount("/proc", config.sysroot / "proc", recursive=True)
        self.bind_mount("/sys", config.sysroot / "sys", recursive=True)
        self.bind_mount("/dev", config.sysroot / "dev", recursive=True)
        self.bind_mount("/run", config.sysroot / "run", recursive=True)
        run(["mount", "--types", "devpts", "devpts", config.sysroot / "dev/pts"], check=True)
