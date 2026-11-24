"""Bounded, process-safe local event log; credentials and command lines stay private."""
import datetime
import json
import os
from pathlib import Path
import threading
import time
import msvcrt
from package_runtime import data_dir

MAX_BYTES = 512 * 1024
_thread_lock = threading.RLock()
_private_keys = {'user', 'username', 'password', 'pwd', 'args', 'command', 'commandline', 'packet', 'challenge'}


def debug_enabled(base=None):
    try:
        folder = Path(base) if base is not None else data_dir()
        return (folder / 'debug_logging.flag').is_file()
    except OSError:
        return False


def set_debug_logging(enabled):
    path = data_dir() / 'debug_logging.flag'
    if enabled:
        path.touch()
    else:
        path.unlink(missing_ok=True)


def _trim_log(path):
    if path.exists() and path.stat().st_size > MAX_BYTES:
        with open(path, 'rb') as stream:
            stream.seek(-MAX_BYTES, os.SEEK_END)
            stream.readline()  # Discard a partial UTF-8/JSON record.
            tail = stream.read()
        temporary = path.with_name(path.name + '.compact.tmp')
        temporary.write_bytes(tail)
        os.replace(temporary, path)


def _clean(value, secrets):
    if isinstance(value, dict):
        return {str(key): '[已隐藏]' if str(key).lower() in _private_keys else _clean(item, secrets)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in sorted(secrets, key=len, reverse=True):
            if secret:
                value = value.replace(secret, '[已隐藏]')
        return value[:1500]
    return value


def event(component, action, *, level='INFO', base=None, **fields):
    folder = Path(base) if base is not None else data_dir()
    if level == 'DEBUG' and not debug_enabled(folder):
        return
    try:
        secrets = (folder / 'config.txt').read_text(encoding='utf-8-sig').split()[:2]
    except OSError:
        secrets = []
    record = _clean(dict(time=datetime.datetime.now().isoformat(timespec='milliseconds'), level=level,
                         pid=os.getpid(), thread=threading.current_thread().name,
                         component=component, event=action, **fields), secrets)
    raw = (json.dumps(record, ensure_ascii=False, default=str) + '\n').encode('utf-8')
    if len(raw) > MAX_BYTES:
        record = {key:record[key] for key in ('time','level','pid','component','event')}
        record.update(component=str(record['component'])[:64], event=str(record['event'])[:128], details_omitted=True)
        raw = (json.dumps(record, ensure_ascii=False) + '\n').encode('utf-8')
        if len(raw) > MAX_BYTES:
            return
    try:
        with _thread_lock, open(folder / 'runtime-log.lock', 'a+b') as lock:
            if lock.seek(0, 2) == 0:
                lock.write(b'0')
                lock.flush()
            acquired = False
            for _ in range(10):
                try:
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    acquired = True
                    break
                except OSError:
                    time.sleep(0.01)
            if not acquired:
                return
            try:
                path = folder / 'runtime.log'
                for name in ('runtime.log.2', 'runtime.log.3'):
                    (folder / name).unlink(missing_ok=True)
                _trim_log(path)
                _trim_log(folder / 'runtime.log.1')
                if path.exists() and path.stat().st_size + len(raw) > MAX_BYTES:
                    os.replace(path, folder / 'runtime.log.1')
                with open(path, 'ab') as stream:
                    stream.write(raw)
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
