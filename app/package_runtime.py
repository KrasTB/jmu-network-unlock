"""Stable data paths and Windows process coordination for the portable app."""
from contextlib import contextmanager
import ctypes
import hashlib
import os
from pathlib import Path
import subprocess
import sys


def data_dir():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent / '程序'
    return Path(__file__).resolve().parent


def app_command(mode):
    if mode not in {'startup-guard', 'auto-switch'}:
        raise ValueError('Unknown application mode')
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--' + mode]
    executable = Path(sys.executable)
    windowless = executable.with_name('pythonw.exe')
    return [str(windowless if windowless.exists() else executable),
            str(data_dir() / 'launcher.py'), '--' + mode]


def command_matches(command, mode):
    """Compare Windows argv, allowing equivalent executable quoting."""
    if not isinstance(command, str) or not command.strip():
        return False
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    count = ctypes.c_int()
    arguments = shell.CommandLineToArgvW(command, ctypes.byref(count))
    if not arguments:
        return False
    try:
        values = [arguments[index] for index in range(count.value)]
        expected = app_command(mode)
        return bool(values) and values[0].casefold() == expected[0].casefold() and values[1:] == expected[1:]
    finally:
        kernel.LocalFree(arguments)


@contextmanager
def instance_lock(kind):
    name = 'Local\\JMU_Shared_' + kind + '_' + hashlib.sha256(
        str(data_dir()).casefold().encode('utf-8')).hexdigest()[:20]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    ctypes.set_last_error(0)
    handle = kernel.CreateMutexW(None, False, name)
    error = ctypes.get_last_error()
    if not handle:
        raise OSError(error, 'Cannot create application mutex')
    try:
        yield error != 183
    finally:
        kernel.CloseHandle(handle)


def ensure_npcap():
    library = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'Npcap' / 'wpcap.dll'
    if library.exists():
        return True
    result = subprocess.run([
        'powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
        str(data_dir() / 'install_npcap.ps1')], creationflags=0x08000000)
    return result.returncode == 0 and library.exists()
