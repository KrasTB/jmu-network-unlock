"""Create and test a clean standalone Windows ZIP from this checkout."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

VERSION = '0.1.0'
ASSETS = ('jmusupplicant.exe', 'libiconv-2.dll', 'getnic.ps1', 'install_npcap.ps1', 'holidays.txt')


def main():
    root = Path(__file__).resolve().parents[1]
    app = root / 'app'
    for name in ASSETS:
        if not (app / name).is_file():
            raise SystemExit('Missing app/' + name + '; run prepare_runtime.py or build_core.py first')
    output = root / 'dist'
    output.mkdir(exist_ok=True)
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed',
                    '--name', '校园网助手', '--paths', str(app), '--distpath', str(output / 'bin'),
                    '--workpath', str(root / 'build' / 'pyinstaller'), '--specpath', str(root / 'build'),
                    str(app / 'launcher.py')], check=True)
    with tempfile.TemporaryDirectory(prefix='发布验收 中文路径-', dir=output) as temporary:
        release = Path(temporary) / '校园网助手'
        data = release / '程序'
        legal = data / '许可'
        legal.mkdir(parents=True)
        shutil.copy2(output / 'bin' / '校园网助手.exe', release / '校园网助手.exe')
        for name in ASSETS:
            shutil.copy2(app / name, data / name)
        shutil.copy2(root / '使用说明.txt', release / '使用说明.txt')
        for name in ['LICENSE', 'NOTICE.md']:
            shutil.copy2(root / name, legal / name)
        for path in (root / 'licenses').glob('*'):
            shutil.copy2(path, legal / path.name)
        runtime = Path(sys.base_prefix)
        for source, name in [(runtime / 'LICENSE.txt', 'Python-LICENSE.txt'),
                              (runtime / 'tcl' / 'tk8.6' / 'license.terms', 'Tk-LICENSE.txt')]:
            if source.is_file():
                shutil.copy2(source, legal / name)
        environment = {key: value for key, value in os.environ.items()
                       if not key.upper().startswith(('PYTHON', 'TCL', 'TK_'))}
        environment['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32')
        report = output / 'selftest.json'
        result = subprocess.run([str(release / '校园网助手.exe'), '--self-test', str(report)],
                                env=environment, check=False, timeout=60)
        if report.exists():
            print(report.read_text(encoding='utf-8'), flush=True)
        else:
            print('The standalone executable did not produce its diagnostic report.', flush=True)
        result.check_returncode()
        assert json.loads(report.read_text(encoding='utf-8'))['ok']
        # Self-test output is never included in the distributed directory.
        archive = output / ('JMU-campus-auth-windows-x64-v' + VERSION + '.zip')
        allowed = [release / '校园网助手.exe', release / '使用说明.txt']
        allowed += [data / name for name in ASSETS]
        allowed += [path for path in legal.iterdir() if path.is_file()]
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
            for path in allowed:
                zipped.write(path, '校园网助手/' + path.relative_to(release).as_posix())
        with zipfile.ZipFile(archive) as zipped:
            assert zipped.testzip() is None
            assert not any(Path(name).name in {'config.txt', 'nic.txt', 'runtime.log', 'runtime-log.lock'}
                           for name in zipped.namelist())
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / 'SHA256SUMS.txt').write_text(checksum + '  ' + archive.name + '\n', encoding='ascii')
    print(json.dumps({'archive': str(archive), 'sha256': checksum}, ensure_ascii=False))


if __name__ == '__main__':
    main()
