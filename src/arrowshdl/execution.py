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
import threading

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
            raise MapError('Timeout must be a positive finite number')
        if _ACTIVE.get():
            return function(*args, **kwargs)
        with tempfile.TemporaryDirectory(prefix='arrowshdl-operation-') as directory:
            request, response = Path(directory)/'request.pkl', Path(directory)/'response.pkl'
            from arrowshdl.progress import _span
            request.write_bytes(pickle.dumps((function.__module__, function.__name__, args, kwargs, _span.get())))
            child = subprocess.Popen([sys.executable, '-m', 'arrowshdl._worker', str(request), str(response)],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=os.name != 'nt')
            errors = []
            def forward(pipe, stream, capture=None):
                for chunk in iter(pipe.readline, b''):
                    if capture is not None: capture.append(chunk)
                    if os.environ.get('ARROWSHDL_PROGRESS') == '1':
                        stream.write(chunk.decode('utf-8', errors='replace').replace('\r\n','\n'))
                        stream.flush()
                pipe.close()
            readers = [threading.Thread(target=forward,args=(child.stdout,sys.stdout),daemon=True),
                       threading.Thread(target=forward,args=(child.stderr,sys.stderr,errors),daemon=True)]
            for reader in readers: reader.start()
            try:
                child.wait(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    os.killpg(child.pid, signal.SIGKILL)
                child.wait()
                for reader in readers: reader.join()
                raise MapError(f'Overall timeout exceeded: {timeout:g} seconds ({function.__name__})') from exc
            for reader in readers: reader.join()
            if not response.is_file():
                raise MapError(b''.join(errors).decode('utf-8', errors='replace')[-4000:] or 'Build process exited without a result')
            success, result = pickle.loads(response.read_bytes())
            if not success:
                raise result
            return result
    return run


def main():
    request, response = map(Path, sys.argv[1:])
    module, name, args, kwargs, span = pickle.loads(request.read_bytes())
    if not module.startswith('arrowshdl.'):
        raise MapError('Unknown operation')
    _ACTIVE.set(True)
    from arrowshdl.progress import _span
    _span.set(span)
    try:
        result = (True, getattr(importlib.import_module(module), name)(*args, **kwargs))
    except Exception as exc:
        result = (False, exc)
    response.write_bytes(pickle.dumps(result))
