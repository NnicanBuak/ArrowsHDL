"""Cross-platform text clipboard support for CLI artifacts."""
import shutil
import subprocess
import sys

from arrowshdl.arrowasm import MapError


def copy_text(value):
    """Copy text to the native clipboard without adding external dependencies."""
    if sys.platform == 'win32':
        command = ['clip.exe']
    elif sys.platform == 'darwin':
        command = ['pbcopy']
    else:
        command = next((candidate for candidate in (('wl-copy',), ('xclip', '-selection', 'clipboard'),
                                                    ('xsel', '--clipboard', '--input'))
                        if shutil.which(candidate[0])), None)
        if command is None:
            raise MapError('Clipboard is unavailable: install wl-clipboard, xclip or xsel')
    try:
        subprocess.run(command, input=value, text=True, encoding='utf-8', check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise MapError(f'Could not copy save to clipboard: {exc}') from exc


__all__ = ['copy_text']
