#!/usr/bin/python3

from aiohttp.web import Application, Response
from asyncio import Lock, sleep, to_thread
from zenlib.logging import loggify
from zenlib.util import get_kwargs
from zenlib.namespace import nsexec

from .genTree import GenTree

class PackageInQueue(Exception):
    pass


@loggify
class GenTreeWeb:
    """Webserver which takes requests at /pkg?pkg=package_name and builds the package on demand."""

    def __init__(self, seed, listen_ip="127.0.0.1", listen_port=8689, **kwargs):
        self.listen_ip = listen_ip
        self.listen_port = listen_port
        self.build_queue = []  # Don't tell anyone the queue is a list
        self.queue_lock = Lock()
        self.genTree = GenTree(name="GenTreeWeb", seed=seed, logger=self.logger)
        self.app = Application(logger=self.logger)
        self.app.on_startup.append(self.app_tasks)
        self.app.router.add_get("/pkg", self.add_package)
        self.app.router.add_static("/", path=self.genTree.config.pkgdir)

    async def enqueue_package(self, package_name):
        async with self.queue_lock:
            if package_name in self.build_queue:
                raise PackageInQueue(f"Package {package_name} is already in the queue.")
            self.build_queue.append(package_name)

    async def add_package(self, request):
        package_name = request.query.get("pkg", None)
        if package_name is None:
            return Response(text="No package name provided", status=400)

        try:
            await self.enqueue_package(package_name)
        except PackageInQueue as e:
            return Response(text=str(e), status=400)

        return Response(text=f"Package added to queue: {package_name}", status=200)

    async def app_tasks(self, app):
        app["build_handler"] = app.loop.create_task(self.handle_queue())

    async def handle_queue(self):
        while True:
            async with self.queue_lock:
                if self.build_queue:
                    package_name = self.build_queue.pop(0)
                else:
                    package_name = None

            if package_name is not None:
                ret = await to_thread(nsexec, self.genTree.build_package, package_name)
                if ret is not None:
                    self.logger.warning("Build process returned: %s", ret)
            else:
                await sleep(1)

    def start(self):
        from aiohttp.web import run_app

        self.logger.debug("Running server on %s:%s", self.listen_ip, self.listen_port)
        run_app(self.app, host=self.listen_ip, port=self.listen_port)


def main():
    arguments = [{"flags": ["seed"], "help": "System seed to use", "action": "store"}]

    kwargs = get_kwargs(package=__package__, description="Builds packages on demand", arguments=arguments)

    server = GenTreeWeb(**kwargs)
    server.start()


if __name__ == "__main__":
    main()
