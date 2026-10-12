"""Bound the complete operation, including Python placement and child processes."""
from contextvars import ContextVar
from functools import wraps
import importlib
import inspect
import math
import os
from pathlib import Path
import pickle
import signal
import subprocess
import sys
import tempfile

from arrowshdl.arrowasm import MapError

_ACTIVE = ContextVar('arrowshdl_operation', default=False)


def bounded(function):
    signature = inspect.signature(function)

    @wraps(function)
    def run(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        timeout = bound.arguments['timeout']
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise MapError('Таймаут должен быть положительным конечным числом')
        if _ACTIVE.get():
            return function(*args, **kwargs)
        with tempfile.TemporaryDirectory(prefix='arrowshdl-operation-') as directory:
            request, response = Path(directory)/'request.pkl', Path(directory)/'response.pkl'
            request.write_bytes(pickle.dumps((function.__module__, function.__name__, args, kwargs)))
            child = subprocess.Popen([sys.executable, '-m', 'arrowshdl._worker', str(request), str(response)],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=os.name != 'nt')
            try:
                stdout, stderr = child.communicate(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    os.killpg(child.pid, signal.SIGKILL)
                child.communicate()
                raise MapError(f'Превышен общий таймаут {timeout:g} с ({function.__name__})') from exc
            if not response.is_file():
                raise MapError(stderr.decode('utf-8', errors='replace')[-4000:] or 'Процесс сборки завершился без результата')
            success, result = pickle.loads(response.read_bytes())
            if not success:
                raise result
            return result
    return run


def main():
    request, response = map(Path, sys.argv[1:])
    module, name, args, kwargs = pickle.loads(request.read_bytes())
    if not module.startswith('arrowshdl.'):
        raise MapError('Неизвестная операция')
    _ACTIVE.set(True)
    try:
        result = (True, getattr(importlib.import_module(module), name)(*args, **kwargs))
    except Exception as exc:
        result = (False, exc)
    response.write_bytes(pickle.dumps(result))
