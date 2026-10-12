"""Phase-weighted progress; stderr is kept separate from command output files."""
from contextlib import contextmanager
from contextvars import ContextVar
import os
import sys
import time

_span = ContextVar('progress_span', default=(0, 100))
_last = 0.0
_printed = None
_stamp = 0.0


def report(percent, message):
    global _last, _printed, _stamp
    if os.environ.get('ARROWSHDL_PROGRESS') != '1':
        return
    start, end = _span.get()
    value = start + (end-start) * max(0, min(100, percent))/100
    _last = max(_last, value)
    item = (round(_last, 1), message)
    now = time.monotonic()
    if message.startswith('Routing:') and now-_stamp < .5:
        return
    if item != _printed:
        print(f'[{_last:5.1f}%] {message}', file=sys.stderr, flush=True)
        _printed = item
        _stamp = now


@contextmanager
def phase(start, end, message):
    low, high = _span.get()
    token = _span.set((low+(high-low)*start/100, low+(high-low)*end/100))
    report(0, message)
    try:
        yield
    finally:
        _span.reset(token)


def reset():
    global _last, _printed
    _last, _printed = 0.0, None
