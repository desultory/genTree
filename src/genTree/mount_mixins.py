from subprocess import run

from zenlib.util import colorize


def bind_mount_repos(method):
    """Binds /var/db/repos over the config root before running the method and unmounts it after"""

    def wrapper(self, *args, **kwargs):
        config = kwargs.get("config")
        if not config and not config.bind_system_repos:
            return method(self, *args, **kwargs)
        self.mount_bind_repos(config)
        ret = method(self, *args, **kwargs)
        self.unmount_bind_repos(config)
        return ret

    return wrapper


class MountMixins:
    def mount_overlay(self, config):
        """Mounts an overlayfs on the build root"""
        config.check_dir([f"{root}_root" for root in ["lower", "work", "upper"]])
        self.logger.info(
            "[%s] Mounting overlayfs on: %s",
            colorize(config.name, "blue"),
            colorize(config.root, "magenta", bold=True),
        )
        run(
            [
                "mount",
                "-t",
                "overlay",
                "overlay",
                "-o",
                f"lowerdir={config.lower_root},upperdir={config.upper_root},workdir={config.work_root}",
                config.root,
            ],
            check=True,
        )

    def mount_bind_repos(self, config):
        """Bind mounts /var/db/repos over the config root"""
        config_repos = self.config.config_root / "var/db/repos"
        if not config_repos.exists():
            config_repos.mkdir(parents=True)
        self.unmount_bind_repos(config)
        self.logger.info(
            "[%s] Mounting /var/db/repos over: %s",
            colorize(config.name, "blue"),
            colorize(config_repos, "magenta"),
        )
        run(["mount", "--bind", "/var/db/repos", config_repos, "-o", "ro"], check=True)

    def unmount_bind_repos(self, config):
        """Unmounts the bind mount of /var/db/repos over the config root"""
        config_repos = self.config.config_root / "var/db/repos"
        if config_repos.is_mount():
            self.logger.info(
                "[%s] Unmounting /var/db/repos: %s",
                colorize(config.name, "blue"),
                colorize(config_repos, "magenta"),
            )
            run(["umount", config_repos], check=True)
