"""Audit platform wheels and produce the checksum manifest for GitHub Releases."""
import argparse
from email.parser import BytesParser
import hashlib
import os
from pathlib import Path
import struct
import sys
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parent.parent
PLATFORMS = {'win_amd64', 'manylinux_2_17_x86_64',
             'macosx_14_0_x86_64', 'macosx_14_0_arm64'}


def windows_imports(binary, pe_offset):
    """Read DLL imports from the x64 PE section table, without extra dependencies."""
    count = struct.unpack_from('<H', binary, pe_offset + 6)[0]
    optional_size = struct.unpack_from('<H', binary, pe_offset + 20)[0]
    optional = pe_offset + 24
    assert struct.unpack_from('<H', binary, optional)[0] == 0x20b, 'Expected PE32+'
    section_table = optional + optional_size

    def offset(rva):
        for index in range(count):
            section = section_table + index * 40
            virtual_size, address, raw_size, raw_offset = struct.unpack_from('<IIII', binary, section + 8)
            if address <= rva < address + max(virtual_size, raw_size):
                return raw_offset + rva - address
        raise AssertionError(f'PE address outside sections: {rva}')

    imports_rva = struct.unpack_from('<I', binary, optional + 112 + 8)[0]
    if not imports_rva:
        return []
    descriptor = offset(imports_rva)
    names = []
    while any(binary[descriptor:descriptor + 20]):
        name = offset(struct.unpack_from('<I', binary, descriptor + 12)[0])
        names.append(binary[name:binary.index(b'\0', name)].decode('ascii').lower())
        descriptor += 20
    return names


def verify(directory):
    version = (ROOT / 'VERSION').read_text().strip()
    for manifest, section in ((ROOT / 'pyproject.toml', 'project'),
                              (ROOT / 'native/Cargo.toml', 'package')):
        assert tomllib.loads(manifest.read_text())[section]['version'] == version
    tag = os.environ.get('RELEASE_TAG')
    if tag:
        assert tag == f'v{version}', (tag, version)
    wheels = sorted(directory.glob('*.whl'))
    assert wheels, 'No wheels found'
    platforms = []
    for wheel in wheels:
        prefix = f'arrowshdl-{version}-py3-none-'
        assert wheel.name.startswith(prefix), wheel.name
        platform = wheel.name[len(prefix):-4]
        assert platform in PLATFORMS, platform
        platforms.append(platform)
        with zipfile.ZipFile(wheel) as archive:
            files = archive.namelist()
            metadata = BytesParser().parsebytes(archive.read(f'arrowshdl-{version}.dist-info/METADATA'))
            assert metadata['Version'] == version
            assert metadata['Requires-Python'] == '>=3.11'
            wheel_metadata = archive.read(f'arrowshdl-{version}.dist-info/WHEEL').decode()
            assert f'Tag: py3-none-{platform}' in wheel_metadata
            assert not any(name.startswith(('tests/', 'examples/')) for name in files)
            assert not any(name.startswith('arrowshdl/data/components/') and name.endswith('.json')
                           for name in files), 'Obsolete JSON component descriptors in wheel'
            for resource in ('runtime/compile-graph.mjs', 'library/arrows.v',
                             'data/components/history64.save.txt',
                             'data/components/seven_segment.save.txt',
                             'data/components/history64.toml',
                             'data/components/seven_segment.toml',
                             'data/licenses/GraphDLC.txt'):
                assert f'arrowshdl/{resource}' in files, resource
            engine = 'arrowshdl/data/native/arrowshdl-engine'
            if platform == 'win_amd64':
                engine += '.exe'
            binary = archive.read(engine)
            assert len(binary) > 10000
            if platform == 'win_amd64':
                assert binary[:2] == b'MZ'
                pe_offset = struct.unpack_from('<I', binary, 0x3c)[0]
                assert binary[pe_offset:pe_offset+4] == b'PE\0\0'
                assert struct.unpack_from('<H', binary, pe_offset+4)[0] == 0x8664
                imports = windows_imports(binary, pe_offset)
                assert not any(name.startswith(('vcruntime', 'msvcp', 'api-ms-win-crt')) or name == 'ucrtbase.dll'
                               for name in imports), f'Windows engine needs an external C runtime: {imports}'
            elif platform.startswith('manylinux'):
                assert binary[:4] == b'\x7fELF' and binary[4] == 2
                assert struct.unpack_from('<H', binary, 18)[0] == 62
                # A static musl executable has no interpreter (PT_INTERP).
                offset = struct.unpack_from('<Q', binary, 32)[0]
                size, count = struct.unpack_from('<HH', binary, 54)
                assert all(struct.unpack_from('<I', binary, offset+i*size)[0] != 3
                           for i in range(count)), 'Linux engine must be static'
            else:
                assert binary[:4] == b'\xcf\xfa\xed\xfe'
                cpu = struct.unpack_from('<I', binary, 4)[0]
                assert cpu == (0x100000c if platform.endswith('arm64') else 0x1000007)
            if platform != 'win_amd64':
                assert archive.getinfo(engine).external_attr >> 16 & 0o111, 'Engine is not executable'
        print(f'PASS: {wheel.name}')
    assert len(platforms) == len(set(platforms)), 'Duplicate platforms'
    return wheels, set(platforms)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('verify', 'manifest'))
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    wheels, platforms = verify(args.directory)
    if args.command == 'manifest':
        assert platforms == PLATFORMS, f'Missing platforms: {PLATFORMS - platforms}'
        lines = [f'{hashlib.sha256(wheel.read_bytes()).hexdigest()}  {wheel.name}\n'
                 for wheel in wheels]
        (args.directory / 'SHA256SUMS.txt').write_text(''.join(lines), encoding='ascii')
        print('PASS: all four platforms; SHA256SUMS.txt generated')


if __name__ == '__main__':
    try:
        main()
    except (AssertionError, KeyError, zipfile.BadZipFile) as error:
        sys.exit(f'Release audit failed: {error}')
