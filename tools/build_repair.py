"""Build the optional standalone updater after tools/build.py."""
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    binary = root / 'dist' / 'bin' / '校园网助手.exe'
    if not binary.is_file():
        raise SystemExit('Run tools/build.py first')
    payload = root / 'build' / 'repair-payload'
    payload.mkdir(parents=True, exist_ok=True)
    shutil.copy2(binary, payload / binary.name)
    shutil.copy2(root / 'app' / 'getnic.ps1', payload / 'getnic.ps1')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed',
                    '--name', 'JMU-network-repair-v0.1.0', '--paths', str(root / 'app'),
                    '--paths', str(root / 'tools'), '--paths', str(root / 'tests'),
                    '--add-data', str(payload) + os.pathsep + 'payload',
                    '--distpath', str(root / 'dist'), '--workpath', str(root / 'build' / 'repair'),
                    '--specpath', str(root / 'build'), str(root / 'tools' / 'repair_launcher.py')], check=True)
    subprocess.run([str(root / 'dist' / 'JMU-network-repair-v0.1.0.exe'), '--self-test',
                    str(root / 'dist' / 'repair-selftest.json')], check=True, timeout=60)


if __name__ == '__main__':
    main()
