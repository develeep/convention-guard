#!/usr/bin/env python3
"""The engine installer, without the network: tags, choosing, verifying, unpacking.

- which wheel fits which interpreter (CPython minor, abi3, glibc/musl, macOS, Windows)
- an install from a local wheel directory: unpacked, self-tested, moved into
  place with READY -- and nothing left behind when any step fails
- a wheel whose sha256 differs from the lock is refused
- a wheel with a member that would land outside the install is refused
- a platform with no wheel is "unsupported", said, not retried
- the loader names why the engine is missing
"""
import hashlib
import io
import json
import os
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import check, finish, tempdir  # noqa: E402
from lib.engine import install, loader, tags  # noqa: E402

LINUX = tags.Interpreter(system='linux', machine='x86_64', minor=12, glibc=(2, 35), musl=None,
                         macos=None, free_threaded=False, implementation='cpython')


def case_tags():
    print('case_tags:')
    fits = lambda interp, name: tags.compatible(interp, name)   # noqa: E731
    check('cp312 on CPython 3.12', fits(LINUX, 'ts-0.25.2-cp312-cp312-manylinux_2_17_x86_64.whl'))
    check('not cp311', not fits(LINUX, 'ts-0.25.2-cp311-cp311-manylinux_2_17_x86_64.whl'))
    check('abi3 from an older minor', fits(LINUX, 'g-0.25.0-cp310-abi3-manylinux_2_17_x86_64.whl'))
    check('but not from a newer one', not fits(LINUX, 'g-1-cp313-abi3-manylinux_2_17_x86_64.whl'))
    check('a dotted platform set: any one fits',
          fits(LINUX, 'g-1-cp39-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl'))
    check('legacy manylinux2014 = glibc 2.17', fits(LINUX, 'g-1-cp39-abi3-manylinux2014_x86_64.whl'))
    check('a newer glibc than this one does not fit',
          not fits(LINUX, 'g-1-cp39-abi3-manylinux_2_39_x86_64.whl'))
    check('another arch does not fit', not fits(LINUX, 'g-1-cp39-abi3-manylinux_2_17_aarch64.whl'))
    check('musllinux needs musl', not fits(LINUX, 'g-1-cp39-abi3-musllinux_1_2_x86_64.whl'))
    musl = tags.Interpreter(system='linux', machine='x86_64', minor=12, glibc=None, musl=(1, 2),
                            free_threaded=False, implementation='cpython')
    check('musl takes musllinux', fits(musl, 'g-1-cp39-abi3-musllinux_1_2_x86_64.whl'))
    mac = tags.Interpreter(system='darwin', machine='arm64', minor=12, macos=(14, 2),
                           free_threaded=False, implementation='cpython')
    check('macOS arm64 takes macosx_11_0_arm64', fits(mac, 'g-1-cp310-abi3-macosx_11_0_arm64.whl'))
    check('and universal2', fits(mac, 'g-1-cp310-abi3-macosx_10_9_universal2.whl'))
    check('not x86_64', not fits(mac, 'g-1-cp310-abi3-macosx_10_9_x86_64.whl'))
    win = tags.Interpreter(system='win32', machine='AMD64', minor=13, free_threaded=False,
                           implementation='cpython')
    check('Windows amd64', fits(win, 'g-1-cp310-abi3-win_amd64.whl'))
    check('not arm64', not fits(win, 'g-1-cp310-abi3-win_arm64.whl'))
    ft = tags.Interpreter(system='linux', machine='x86_64', minor=13, glibc=(2, 35),
                          free_threaded=True, implementation='cpython')
    check('a free-threaded build takes none', not fits(ft, 'g-1-cp310-abi3-manylinux_2_17_x86_64.whl'))
    check('the platform key names the install directory', LINUX.platform_key() == 'cp312-linux-x86_64')


def wheel(files):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        for name, body in files.items():
            archive.writestr(name, body)
    return data.getvalue()


def fake_lock(wheels_dir, entries):
    """lock.json shape for wheels written into `wheels_dir`."""
    packages = []
    for name, filename, files, sha in entries:
        data = wheel(files)
        with open(os.path.join(wheels_dir, filename), 'wb') as fh:
            fh.write(data)
        packages.append({'name': name, 'version': '1', 'module': name.replace('-', '_'),
                         'files': [{'filename': filename, 'url': install.HOST + filename,
                                    'sha256': sha or hashlib.sha256(data).hexdigest()}]})
    return {'packages': packages}


GOOD = 'tree_sitter-1-cp312-cp312-manylinux_2_17_x86_64.whl'


def case_offline_install():
    print('case_offline_install:')
    with tempdir() as tmp:
        wheels, base = os.path.join(tmp, 'w'), os.path.join(tmp, 'engine')
        os.makedirs(wheels)
        lock = fake_lock(wheels, [('tree-sitter', GOOD, {'tree_sitter/__init__.py': 'X = 1\n'},
                                   None)])
        tested = []
        path = install.ensure(base=base, wheels_dir=wheels, interp=LINUX, lock=lock,
                              self_test=tested.append)
        check('it installs into <lock id>/<platform key>',
              path == os.path.join(base, install.lock_id(lock), 'cp312-linux-x86_64'), path)
        check('the wheel is unpacked', os.path.isfile(os.path.join(path, 'tree_sitter',
                                                                   '__init__.py')))
        check('it was self-tested before being moved in', len(tested) == 1)
        check('READY marks it done', os.path.isfile(os.path.join(path, 'READY')))
        check('and status says ok', install.read_status(base).get('state') == 'ok')
        check('nothing temporary is left',
              [n for n in os.listdir(os.path.dirname(path)) if n.startswith('.install-')] == [])
        again = install.ensure(base=base, wheels_dir=wheels, interp=LINUX, lock=lock,
                               self_test=lambda d: tested.append(d))
        check('a second ensure does nothing', again == path and len(tested) == 1)


def expect_refusal(label, lock_entries, needle):
    with tempdir() as tmp:
        wheels, base = os.path.join(tmp, 'w'), os.path.join(tmp, 'engine')
        os.makedirs(wheels)
        lock = fake_lock(wheels, lock_entries)
        try:
            install.ensure(base=base, wheels_dir=wheels, interp=LINUX, lock=lock,
                           self_test=lambda d: None)
        except install.InstallError as exc:
            check(label, needle in str(exc), str(exc))
            check('%s: nothing is installed' % label,
                  install.installed(lock, LINUX, base) is None)
            check('%s: the failure is recorded' % label,
                  install.read_status(base).get('state') in ('failed', 'unsupported'))
            return
        check(label, False, 'no error')


def case_refusals():
    print('case_refusals:')
    expect_refusal('a sha256 that differs from the lock is refused',
                   [('tree-sitter', GOOD, {'a.py': ''}, 'f' * 64)], 'sha256')
    expect_refusal('a member outside the install is refused',
                   [('tree-sitter', GOOD, {'../escape.py': 'x'}, None)], '경로 탈출')
    expect_refusal('an absolute member is refused',
                   [('tree-sitter', GOOD, {'/etc/x.py': 'x'}, None)], '경로 탈출')
    expect_refusal('no wheel for this platform is unsupported',
                   [('tree-sitter', 'tree_sitter-1-cp312-cp312-win_amd64.whl', {'a.py': ''},
                     None)], 'unsupported')

    with tempdir() as tmp:
        wheels, base = os.path.join(tmp, 'w'), os.path.join(tmp, 'engine')
        os.makedirs(wheels)
        lock = fake_lock(wheels, [('tree-sitter', GOOD, {'a.py': ''}, None)])

        def broken(_directory):
            raise install.InstallError('self-test: ImportError')
        try:
            install.ensure(base=base, wheels_dir=wheels, interp=LINUX, lock=lock, self_test=broken)
            check('a failed self-test fails the install', False)
        except install.InstallError:
            check('a failed self-test leaves nothing installed',
                  install.installed(lock, LINUX, base) is None)
    bad_host = {'filename': GOOD, 'url': 'https://example.com/' + GOOD, 'sha256': '0' * 64}
    with tempdir() as tmp:
        try:
            install._fetch(bad_host, tmp)
            check('only files.pythonhosted.org is fetched from', False)
        except install.InstallError as exc:
            check('only files.pythonhosted.org is fetched from', '허용하지 않는 주소' in str(exc))


def case_real_lock():
    print('case_real_lock:')
    lock = install.read_lock()
    names = [p['name'] for p in lock['packages']]
    check('the lock pins the core and four grammars',
          names == [n for n, _v, _m in install.PINS], names)
    check('every wheel has a sha256 and a pythonhosted url',
          all(len(w['sha256']) == 64 and w['url'].startswith(install.HOST)
              for p in lock['packages'] for w in p['files']))
    for label, interp in (('linux x86_64 3.10', tags.Interpreter(system='linux', machine='x86_64',
                                                                   minor=10, glibc=(2, 17))),
                          ('linux aarch64 3.14', tags.Interpreter(system='linux', machine='aarch64',
                                                                    minor=14, glibc=(2, 28))),
                          ('macOS arm64 3.12', tags.Interpreter(system='darwin', machine='arm64',
                                                                  minor=12, macos=(13, 0))),
                          ('Windows amd64 3.13', tags.Interpreter(system='win32', machine='AMD64',
                                                                    minor=13))):
        interp.free_threaded, interp.implementation = False, 'cpython'
        try:
            chosen = install.choose(lock, interp)
            check('%s has every wheel' % label, len(chosen) == len(lock['packages']))
        except install.InstallError as exc:
            check('%s has every wheel' % label, False, str(exc))
    old = tags.Interpreter(system='linux', machine='x86_64', minor=9, glibc=(2, 31),
                           free_threaded=False, implementation='cpython')
    try:
        install.choose(lock, old)
        check('Python 3.9 has no core wheel', False)
    except install.InstallError as exc:
        check('Python 3.9 has no core wheel', 'tree-sitter' in str(exc), str(exc))


def case_kick_and_loader():
    print('case_kick_and_loader:')
    with tempdir() as tmp:
        saved = {k: os.environ.get(k) for k in ('CONVENTION_GUARD_ENGINE_DIR',
                                                 'CONVENTION_GUARD_NO_ENGINE')}
        os.environ['CONVENTION_GUARD_ENGINE_DIR'] = tmp
        os.environ.pop('CONVENTION_GUARD_NO_ENGINE', None)
        try:
            loader.reset()
            missing = loader.get()
            check('an empty engine dir is "not installed"',
                  not missing.ok and missing.reason == 'not_installed', missing.describe())
            install.write_status('failed', 'download: x', tmp)
            loader.reset()
            check('a failed attempt is said with its reason',
                  loader.get().reason == 'failed' and 'download' in loader.get().describe())
            check('and is not retried within RETRY_AFTER', install.kick('/nonexistent.py') is False)
            os.environ['CONVENTION_GUARD_NO_ENGINE'] = '1'
            loader.reset()
            check('CONVENTION_GUARD_NO_ENGINE turns it off', loader.get().reason == 'disabled')
            check('and is never kicked', install.kick('/nonexistent.py') is False)
            os.environ.pop('CONVENTION_GUARD_NO_ENGINE')
            status = install.read_status(tmp)
            status['at'] = time.time() - install.RETRY_AFTER - 5
            with open(install.status_path(tmp), 'w', encoding='utf-8') as fh:
                json.dump(status, fh)
            install.write_status('unsupported', 'unsupported: x', tmp)
            check('an unsupported platform is never kicked', install.kick('/nonexistent.py') is False)
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            loader.reset()


if __name__ == '__main__':
    for case in (case_tags, case_offline_install, case_refusals, case_real_lock,
                 case_kick_and_loader):
        case()
    sys.exit(finish('구조 엔진 설치기'))
