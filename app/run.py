import asyncio
import os
from functools import partial

import click
from aiohttp import ClientSession
from arq import RunWorkerProcess
from gunicorn.app.base import BaseApplication

from .logs import logger
from .main import create_app
from .management import prepare_database
from .settings import load_settings

commands = []


def command(func):
    commands.append(func)
    return func


async def _check_port_open(conf, loop):
    host, port = conf['host'], conf['port']
    steps, delay = 100, 0.1
    for i in range(steps):
        try:
            await loop.create_connection(lambda: asyncio.Protocol(), host=host, port=port)
        except OSError:
            await asyncio.sleep(delay, loop=loop)
        else:
            logger.info('Connected successfully to %s:%s after %0.2fs', host, port, delay * i)
            return
    raise RuntimeError(f'Unable to connect to {host}:{port} after {steps * delay}s')


def check_services_ready(*, postgres=True, redis=True):
    settings = load_settings()
    loop = asyncio.get_event_loop()
    coros = []
    if postgres:
        coros.append(_check_port_open(settings['database'], loop))
    if redis:
        coros.append(_check_port_open(settings['redis'], loop))
    loop.run_until_complete(asyncio.gather(*coros, loop=loop))


def check_app():
    loop = asyncio.get_event_loop()
    logger.info("initialising aiohttp app to check it's working...")
    app = create_app(loop)
    loop.run_until_complete(app.startup())
    loop.run_until_complete(app.cleanup())
    del app
    logger.info('app started and stopped successfully, apparently configured correctly')


@command
def web(**kwargs):
    """
    Serve the application

    If the database doesn't already exist it will be created.
    """
    logger.info('waiting for postgres and redis to come up...')
    check_services_ready()

    logger.info('preparing the database...')
    prepare_database(False, print_func=logger.info)

    check_app()

    config = dict(
        worker_class='aiohttp.worker.GunicornUVLoopWebWorker',
        bind=os.getenv('BIND', '127.0.0.1:8000'),
        max_requests=5000,
        max_requests_jitter=500,
    )

    class Application(BaseApplication):
        def load_config(self):
            for k, v in config.items():
                self.cfg.set(k, v)

        def load(self):
            loop = asyncio.get_event_loop()
            return create_app(loop)

    logger.info('starting gunicorn...')
    Application().run()


async def _check_web_coro(url):
    try:
        async with ClientSession() as session:
            async with session.get(url) as r:
                assert r.status == 200, f'response error {r.status} != 200'
    except (ValueError, AssertionError, OSError) as e:
        logger.error('web check error: %s: %s, url: "%s"', e.__class__.__name__, e, url)
        return 1
    else:
        logger.info('web check successful')


def _check_web():
    url = 'http://' + os.getenv('BIND', '127.0.0.1:8000')
    loop = asyncio.get_event_loop()
    exit_code = loop.run_until_complete(_check_web_coro(url))
    if exit_code:
        exit(exit_code)


def _check_worker():
    # TODO
    logger.warning('worker check not yet implemented')


@command
def check(**kwargs):
    """
    Check the application is running correctly, what this does depends on the CHECK environment variable
    """
    check_mode = os.getenv('CHECK')
    if check_mode == 'web':
        _check_web()
    elif check_mode == 'worker':
        _check_worker()
    else:
        raise ValueError('to use this the "CHECK" environment variable should be set to "web" or "worker"')


@command
def worker(**kwargs):
    """
    Run the worker
    """
    logger.info('waiting for redis to come up...')
    check_services_ready(postgres=False)
    RunWorkerProcess('app/worker.py', 'Worker')


@command
def resetdb(*, no_input, **kwargs):
    """
    create a database and run migrations, optionally deleting an existing database.
    """
    delete = no_input or partial(click.confirm, 'Are you sure you want to delete the database and recreate it?')
    prepare_database(delete, print_func=logger.info)