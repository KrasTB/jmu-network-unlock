"""Copy only verified runtime binaries out of a same-version Windows release ZIP."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    hashes = json.loads((root / 'core' / 'binary-manifest.json').read_text(encoding='utf-8'))
    with zipfile.ZipFile(args.archive) as archive:
        for name, expected in hashes.items():
            matches = [item for item in archive.namelist() if item.endswith('/程序/' + name)]
            if len(matches) != 1:
                raise ValueError('Archive must contain exactly one ' + name)
            data = archive.read(matches[0])
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError('Checksum mismatch for ' + name)
            (root / 'app' / name).write_bytes(data)
    print('Verified runtime binaries prepared in app/')


if __name__ == '__main__':
    main()
