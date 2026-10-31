"""Verify the locked, license-bearing pure-Python portable HTTP/2 additions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def verify() -> int:
    lock = json.loads((ROOT / 'scripts/custom/http2-runtime-lock.json').read_text())
    vendor = ROOT / 'customization/packages/octop/_vendor/http2'
    expected = {}
    for package in lock['packages']:
        if package['license'] != 'MIT':
            raise ValueError('Unexpected dependency license')
        for name, digest in package['files'].items():
            relative = Path(name)
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('Invalid locked dependency path')
            expected[name] = digest
    actual = {
        file.relative_to(vendor).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
        for file in vendor.rglob('*')
        if file.is_file() and '__pycache__' not in file.parts and file.suffix != '.pyc'
    }
    if actual != expected:
        raise ValueError('Portable HTTP/2 dependency files differ from their lock')
    for package in lock['packages']:
        if not any('LICENSE' in name.upper() for name in package['files']):
            raise ValueError('Dependency license notice is missing')
    return len(actual)


if __name__ == '__main__':
    print(f'Verified {verify()} locked HTTP/2 files and their MIT license notices.')
