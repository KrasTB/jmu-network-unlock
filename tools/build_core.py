"""Build the Windows port with MinGW-w64 and the user's Npcap SDK."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sdk', type=Path, required=True)
    parser.add_argument('--gcc', default='gcc')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    compiler = shutil.which(args.gcc)
    if not compiler:
        raise SystemExit('MinGW-w64 gcc was not found')
    compiler = Path(compiler).resolve()
    library = args.sdk.resolve() / 'Lib' / 'x64' / 'wpcap.lib'
    if not library.is_file():
        raise SystemExit('Npcap SDK x64 import library was not found')
    output = root / 'build' / 'core'
    output.mkdir(parents=True, exist_ok=True)
    source = root / 'core' / 'src'
    compat = root / 'core' / 'compat'
    environment = os.environ.copy()
    environment['PATH'] = str(compiler.parent) + os.pathsep + environment.get('PATH', '')
    objects = []
    for file in sorted(source.glob('*.c')) + sorted((source / 'mentohust_encryption').glob('*.c')):
        obj = output / (file.stem + '.o')
        subprocess.run([str(compiler), '-O2', '-w', '-I' + str(args.sdk.resolve() / 'Include'),
                        '-I' + str(compat), '-I' + str(source), '-I' + str(source / 'mentohust_encryption'),
                        '-include', str(compat / 'winposix.h'), '-c', str(file), '-o', str(obj)],
                       env=environment, check=True)
        objects.append(str(obj))
    binary = output / 'jmusupplicant.exe'
    subprocess.run([str(compiler), '-o', str(binary), *objects, str(library), '-liconv', '-lws2_32', '-liphlpapi'],
                   env=environment, check=True)
    shutil.copy2(binary, root / 'app' / binary.name)
    shutil.copy2(compiler.parent / 'libiconv-2.dll', root / 'app' / 'libiconv-2.dll')
    print('Compiled core and DLL prepared in app/; no authentication was run')


if __name__ == '__main__':
    main()
