"""Which wheels this interpreter can load, without `packaging`.

A wheel's name ends in `<python tag>-<abi tag>-<platform tag>.whl`, each of
which may be a dotted set (`manylinux2014_x86_64.manylinux_2_17_x86_64`).
The engine only ships CPython extension wheels, so this answers exactly the
questions those raise:

    python/abi   cp312-cp312 (this minor only) or cp39-abi3 (this minor or older)
    platform     manylinux_X_Y / manylinux2014 / manylinux1 (glibc >= X.Y),
                 musllinux_X_Y (musl >= X.Y), macosx_X_Y (macOS >= X.Y, same
                 arch or universal2), win_amd64 / win_arm64

`describe()` names the platform for messages and for the install directory.
"""

import os
import platform
import re
import subprocess
import sys
import sysconfig

LEGACY_MANYLINUX = {'manylinux1': (2, 5), 'manylinux2010': (2, 12), 'manylinux2014': (2, 17)}
ARCH_ALIASES = {'amd64': 'x86_64', 'x64': 'x86_64', 'arm64': 'aarch64', 'aarch64': 'aarch64'}


class Interpreter:
    """What a wheel has to match. Built from this process unless given."""

    def __init__(self, system=None, machine=None, minor=None, glibc=None, musl=None,
                 macos=None, free_threaded=None, implementation=None):
        self.system = system or sys.platform
        self.machine = (machine or platform.machine() or '').lower()
        self.minor = minor if minor is not None else sys.version_info[1]
        self.implementation = implementation or sys.implementation.name
        self.free_threaded = (bool(sysconfig.get_config_var('Py_GIL_DISABLED'))
                              if free_threaded is None else free_threaded)
        if self.system.startswith('linux'):
            self.glibc = glibc if glibc is not None else _glibc()
            self.musl = musl if musl is not None else (None if self.glibc else _musl())
        else:
            self.glibc = self.musl = None
        self.macos = macos if macos is not None else (_macos() if self.system == 'darwin'
                                                      else None)

    @property
    def arch(self):
        return ARCH_ALIASES.get(self.machine, self.machine)

    def platform_key(self):
        """'cp312-linux-x86_64' -- one install directory per answer."""
        osname = {'darwin': 'macos', 'win32': 'windows'}.get(self.system, 'linux')
        if osname == 'linux' and self.musl:
            osname = 'musl'
        return 'cp3%d-%s-%s' % (self.minor, osname, self.arch)


def _glibc():
    try:
        name = os.confstr('CS_GNU_LIBC_VERSION') or ''
    except (AttributeError, ValueError, OSError):
        name = ''
    match = re.match(r'glibc (\d+)\.(\d+)', name)
    return (int(match.group(1)), int(match.group(2))) if match else None


def _musl():
    """musl prints its version on stderr when its loader is run with no arguments."""
    for loader in sorted(os.listdir('/lib')) if os.path.isdir('/lib') else ():
        if loader.startswith('ld-musl-'):
            try:
                proc = subprocess.run([os.path.join('/lib', loader)], capture_output=True,
                                      text=True, timeout=5)
            except (OSError, subprocess.SubprocessError):
                return (1, 1)
            match = re.search(r'Version (\d+)\.(\d+)', proc.stderr)
            return (int(match.group(1)), int(match.group(2))) if match else (1, 1)
    return None


def _macos():
    release = platform.mac_ver()[0]
    parts = [int(p) for p in release.split('.')[:2] if p.isdigit()]
    if not parts:
        return None
    return (parts[0], parts[1] if len(parts) > 1 else 0)


def parse(filename):
    """'name-1.0-cp39-abi3-win_amd64.whl' -> (name, version, pythons, abis, platforms)."""
    stem = filename[:-4] if filename.endswith('.whl') else filename
    parts = stem.split('-')
    if len(parts) < 5:
        raise ValueError('wheel 파일 이름이 아닙니다: %s' % filename)
    name, version = parts[0], parts[1]
    pythons, abis, platforms = parts[-3].split('.'), parts[-2].split('.'), parts[-1].split('.')
    return name, version, pythons, abis, platforms


def python_ok(interp, pythons, abis):
    if interp.implementation != 'cpython' or interp.free_threaded:
        return False                    # no wheel targets these (design §4.1)
    for py in pythons:
        match = re.match(r'cp3(\d+)$', py)
        if not match:
            continue
        minor = int(match.group(1))
        if 'abi3' in abis and minor <= interp.minor:
            return True
        if minor == interp.minor and ('cp3%d' % minor) in abis:
            return True
    return False


def platform_ok(interp, platforms):
    return any(_one_platform(interp, tag) for tag in platforms)


def _one_platform(interp, tag):
    if tag == 'any':
        return True
    if interp.system == 'win32':
        return tag == {'x86_64': 'win_amd64', 'aarch64': 'win_arm64'}.get(interp.arch)
    if interp.system == 'darwin':
        match = re.match(r'macosx_(\d+)_(\d+)_(\w+)$', tag)
        if not match or interp.macos is None:
            return False
        arch = match.group(3)
        want = {'aarch64': 'arm64'}.get(interp.arch, interp.arch)
        return (arch in (want, 'universal2')
                and (int(match.group(1)), int(match.group(2))) <= interp.macos)
    if interp.system.startswith('linux'):
        for prefix, libc in (('manylinux', interp.glibc), ('musllinux', interp.musl)):
            if libc is None or not tag.startswith(prefix):
                continue
            match = re.match(r'%s_(\d+)_(\d+)_(\w+)$' % prefix, tag)
            if match:
                needed, arch = (int(match.group(1)), int(match.group(2))), match.group(3)
            else:
                legacy = re.match(r'(manylinux\d+)_(\w+)$', tag)
                if not legacy or legacy.group(1) not in LEGACY_MANYLINUX:
                    continue
                needed, arch = LEGACY_MANYLINUX[legacy.group(1)], legacy.group(2)
            if arch == interp.arch and needed <= libc:
                return True
    return False


def compatible(interp, filename):
    try:
        _name, _version, pythons, abis, platforms = parse(filename)
    except ValueError:
        return False
    return python_ok(interp, pythons, abis) and platform_ok(interp, platforms)


def describe(interp):
    """Human words for the platform, for "미지원 플랫폼 (…)"."""
    extra = ' free-threaded' if interp.free_threaded else ''
    libc = (' glibc %d.%d' % interp.glibc if interp.glibc else
            ' musl %d.%d' % interp.musl if interp.musl else
            ' macOS %d.%d' % interp.macos if interp.macos else '')
    return 'Python 3.%d%s, %s %s%s' % (interp.minor, extra, interp.system, interp.arch, libc)
