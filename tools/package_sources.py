"""Package tracked source plus the verified libiconv corresponding-source tarball."""
import hashlib
from pathlib import Path
import subprocess
import urllib.request
import zipfile

VERSION = '0.1.2'
ICONV_SHA256 = '88dd96a8c0464eca144fc791ae60cd31cd8ee78321e67397e25fc095c4a19aa6'


def main():
    root = Path(__file__).resolve().parents[1]
    iconv = root / 'third_party' / 'libiconv' / 'libiconv-1.19.tar.gz'
    if not iconv.exists():
        with urllib.request.urlopen('https://ftp.gnu.org/pub/gnu/libiconv/libiconv-1.19.tar.gz', timeout=60) as response:
            iconv.write_bytes(response.read())
    if hashlib.sha256(iconv.read_bytes()).hexdigest() != ICONV_SHA256:
        raise ValueError('libiconv source checksum mismatch')
    files = subprocess.run(['git', 'ls-files', '-z'], cwd=root, capture_output=True, check=True).stdout.decode('utf-8').split('\0')
    paths = [root / name for name in files if name and not name.startswith('vendor/runtime/')]
    paths.append(iconv)
    output = root / 'dist'
    output.mkdir(exist_ok=True)
    archive = output / ('JMU-night-network-complete-source-v' + VERSION + '.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
        for path in paths:
            zipped.write(path, 'jmu-network-unlock-' + VERSION + '/' + path.relative_to(root).as_posix())
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.testzip() is None
    print(archive)


if __name__ == '__main__':
    main()
