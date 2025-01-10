from pathlib import Path
from shutil import rmtree
from subprocess import CalledProcessError, run

from zenlib.util import colorize


class MountMixins:
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

        config.logger.info(
            " =-= [%s] Mounting config overlay on: %s", colorize(config.name, "green"), colorize(config_dir, "blue")
        )
        self.overlay_mount("/etc/portage", config_dir)

    def mount_seed_overlay(self):
        """Mounts an overlayfs on the seed root"""
        if not self.config.seed_root.exists():
            raise FileNotFoundError(f"Seed root not found: {self.config.seed_root}")

        if self.config.no_seed_overlay:
            return self.logger.warning(" !-! Skipping seed overlay creation.")

        temp = self.config.ephemeral_seed
        clean = self.config.clean_seed
        self.overlay_mount(self.config.sysroot, self.config.seed_root, temp=temp, clean=clean)

    def tmpfs_mount(self, mountpoint: Path, size: int = 0, mode: str = "rw"):
        """Creates a tmpfs mount at the specified mountpoint with the specified size and mode.
        If size is 0, the size is unlimited.
        """
        mountpoint = Path(mountpoint)
        if not mountpoint.exists():
            self.logger.debug("[tmpfs] Creating mountpoint: %s", mountpoint)
            mountpoint.mkdir(parents=True)

        args = ["mount", "-t", "tmpfs", "tmpfs", mountpoint]
        if size:
            args.extend(["-o", f"size={size}"])
        if mode:
            args.extend(["-o", mode])

        self.logger.info(" +/~ Mounting tmpfs on: %s", colorize(mountpoint, "yellow"))
        run(args, check=True)

    def overlay_mount(
        self,
        mountpoint: Path,
        lower: Path,
        work: Path = None,
        upper: Path = None,
        userxattr=True,
        temp=False,
        clean=False,
    ):
        """Mounts an overlayfs using the specified lower dir and mountpint.
        If an upper or work directory is not specified, they will be created in the same directory as the lower dir
        with the names .<lower_name>_upper and .<lower_name>_work respectively.

        If temp is set, creates .<lower_name>_temp, mounts a tmpfs over it, then uses it for the upper and work dirs.
        if clean is set, the upper and work directories will be cleared before mounting.
        """
        mountpoint, lowerdir = Path(mountpoint), Path(lower)
        if not lowerdir.exists():
            raise FileNotFoundError(f"Lower directory not found: {lowerdir}")
        if not mountpoint.exists():
            self.logger.debug("[overlay] Creating mountpoint: %s", mountpoint)
            mountpoint.mkdir(parents=True)
        elif mountpoint.is_mount():
            self.logger.info(" - - Unmounting overlay on: %s", mountpoint)
            run(["umount", mountpoint], check=True)

        if temp:
            tmpdir = lowerdir.with_name(f".{lowerdir.name}_temp")
            self.tmpfs_mount(tmpdir)
            upper = tmpdir / "upper"
            work = tmpdir / "work"
        else:
            upper = Path(upper) if upper else lowerdir.with_name(f".{lowerdir.name}_upper")
            work = Path(work) if work else lowerdir.with_name(f".{lowerdir.name}_work")

        if clean:
            for d in [upper, work]:
                if d.exists():
                    self.logger.warning(" --- Cleaning directory: %s", (colorize(d, "yellow")))
                    rmtree(d)

        if not upper.exists():
            self.logger.debug("[overlay] Creating upper directory: %s", upper)
            upper.mkdir(parents=True)
        if not work.exists():
            self.logger.debug("[overlay] Creating work directory: %s", work)
            work.mkdir(parents=True)

        options = "userxattr," if userxattr else ""
        options += f"lowerdir={lowerdir},upperdir={upper},workdir={work}"
        args = ["mount", "-t", "overlay", "overlay", "-o", options, str(mountpoint)]
        self.logger.info(" ~/* Mounting overlay on: %s", colorize(mountpoint, "cyan", bold=True))
        run(args, check=True)

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
