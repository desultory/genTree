from subprocess import run

from zenlib.util import colorize


class MountMixins:
    def mount_root_overlay(self, config):
        """Mounts an overlayfs on the build root"""
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
                f"userxattr,lowerdir={config.lower_root},upperdir={config.upper_root},workdir={config.work_root}",
                config.root,
            ],
            check=True,
        )

    def mount_seed_overlay(self):
        """Mounts an overlayfs on the seed root"""
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

    def bind_mount_repos(self, config):
        """Bind mounts the configured repo dir over the upper seed root"""
        repo_dest = self.config.sysroot / "var/db/repos"
        if not repo_dest.exists():
            repo_dest.mkdir(parents=True)
        self.unmount_bind_repos(config)
        self.logger.info(
            "Mounting %s over: %s", colorize(config.system_repos, "green"), colorize(repo_dest, "magenta")
        )
        run(["mount", "--bind", config.system_repos, repo_dest, "-o", "ro"], check=True)

    def unmount_bind_repos(self, config):
        """Unmounts the repor dir bind mount over the upper seed root if it exists"""
        repo_dest = self.config.sysroot / "var/db/repos"
        if repo_dest.is_mount():
            self.logger.info(
                "Unmounting %s: %s", colorize(config.system_repos, "red"), colorize(repo_dest, "magenta")
            )
            run(["umount", repo_dest], check=True)
