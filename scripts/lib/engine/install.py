"""Install the structure engine with nothing but the standard library.

No venv, no pip: a Debian python3 often has neither, and PEP 668 forbids pip
on the system interpreter anyway. The pinned wheels in lock.json are fetched
from files.pythonhosted.org (or a local directory), checked against their
sha256, unpacked into

    <engine dir>/<lock id>/<cp3XY-os-arch>/

and imported straight from there by loader.py. A finished directory holds a
READY file; nothing else counts as installed. The install is tried in a
temporary directory first -- import every grammar, parse a line -- and only
then moved into place, so a half-written engine is never loaded.

<engine dir> is `$CLAUDE_PLUGIN_DATA/engine`, or $CONVENTION_GUARD_ENGINE_DIR.
`status.json` there records the last attempt, which the Stop reads to say why
the engine is missing and whether to try again.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

from . import tags
from ..paths import data_dir

HERE = os.path.dirname(os.path.abspath(__file__))
LOCK = os.path.join(HERE, 'lock.json')
PINS = (('tree-sitter', '0.25.2', 'tree_sitter'),
        ('tree-sitter-javascript', '0.25.0', 'tree_sitter_javascript'),
        ('tree-sitter-typescript', '0.23.2', 'tree_sitter_typescript'),
        ('tree-sitter-php', '0.24.1', 'tree_sitter_php'),
        ('tree-sitter-python', '0.25.0', 'tree_sitter_python'))
HOST = 'https://files.pythonhosted.org/'
DOWNLOAD_TIMEOUT = 60
LOCK_STALE = 600            # an install lock older than this was left by a killed process
RETRY_AFTER = 600           # seconds before a failed install is tried again on its own

# what a finished install must be able to do
SELF_TEST = (
    'import sys\n'
    'sys.path.insert(0, sys.argv[1])\n'
    'import tree_sitter as ts\n'
    'import tree_sitter_javascript, tree_sitter_typescript, tree_sitter_php, tree_sitter_python\n'
    'for capsule in (tree_sitter_javascript.language(), tree_sitter_typescript.language_typescript(),\n'
    '                tree_sitter_typescript.language_tsx(), tree_sitter_php.language_php(),\n'
    '                tree_sitter_php.language_php_only(), tree_sitter_python.language()):\n'
    '    tree = ts.Parser(ts.Language(capsule)).parse(b"x")\n'
    '    assert tree.root_node is not None\n'
    'print("ok")\n')


class InstallError(Exception):
    pass


# ---------------------------------------------------------------- where

def base_dir():
    env = os.environ.get('CONVENTION_GUARD_ENGINE_DIR')
    return os.path.abspath(env) if env else os.path.join(data_dir(), 'engine')


def read_lock(path=LOCK):
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def lock_id(lock):
    digest = hashlib.sha256()
    for package in lock['packages']:
        digest.update(('%s==%s\n' % (package['name'], package['version'])).encode())
        for wheel in sorted(package['files'], key=lambda f: f['filename']):
            digest.update(wheel['sha256'].encode())
    return digest.hexdigest()[:12]


def target_dir(lock, interp=None, base=None):
    interp = interp or tags.Interpreter()
    return os.path.join(base or base_dir(), lock_id(lock), interp.platform_key())


def choose(lock, interp=None):
    """{package: wheel} for this interpreter, or InstallError naming what has none."""
    interp = interp or tags.Interpreter()
    chosen, missing = {}, []
    for package in lock['packages']:
        fits = [w for w in package['files'] if tags.compatible(interp, w['filename'])]
        if not fits:
            missing.append(package['name'])
            continue
        # the most specific first: a cp3XY wheel over abi3, a newer platform over an older
        fits.sort(key=lambda w: ('abi3' in w['filename'], w['filename']))
        chosen[package['name']] = fits[0]
    if missing:
        raise InstallError('unsupported: %s 에 맞는 휠이 없음 (%s)'
                           % (tags.describe(interp), ', '.join(missing)))
    return chosen


# ---------------------------------------------------------------- status

def status_path(base=None):
    return os.path.join(base or base_dir(), 'status.json')


def read_status(base=None):
    try:
        with open(status_path(base), 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_status(state, reason='', base=None, **extra):
    path = status_path(base)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = '%s.%d.tmp' % (path, os.getpid())
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(dict(extra, state=state, reason=reason, at=time.time(),
                           key=tags.Interpreter().platform_key()), fh, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass


# ---------------------------------------------------------------- getting wheels

def _fetch(wheel, dest_dir, wheels_dir=None):
    """The wheel's bytes on disk, sha256 checked. Returns the path."""
    target = os.path.join(dest_dir, wheel['filename'])
    local = os.path.join(wheels_dir, wheel['filename']) if wheels_dir else None
    digest = hashlib.sha256()
    if local:
        if not os.path.isfile(local):
            raise InstallError('오프라인 휠 디렉터리에 %s 가 없음' % wheel['filename'])
        with open(local, 'rb') as src, open(target, 'wb') as out:
            for chunk in iter(lambda: src.read(65536), b''):
                digest.update(chunk)
                out.write(chunk)
    else:
        if not wheel['url'].startswith(HOST):
            raise InstallError('허용하지 않는 주소: %s' % wheel['url'])
        import urllib.request       # only an install pays for it, never a Stop
        try:
            with urllib.request.urlopen(wheel['url'], timeout=DOWNLOAD_TIMEOUT) as resp, \
                    open(target, 'wb') as out:
                for chunk in iter(lambda: resp.read(65536), b''):
                    digest.update(chunk)
                    out.write(chunk)
        except OSError as exc:
            raise InstallError('download: %s 를 받지 못함 (%s)' % (wheel['filename'], exc))
    if digest.hexdigest() != wheel['sha256']:
        raise InstallError('sha256: %s 의 해시가 lock 과 다름' % wheel['filename'])
    return target


def _unpack(path, dest):
    """Unzip a wheel, refusing any member that would land outside `dest`."""
    root = os.path.realpath(dest)
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            name = member.filename
            if name.startswith(('/', '\\')) or '..' in name.replace('\\', '/').split('/') \
                    or os.path.isabs(name) or ':' in name.split('/')[0]:
                raise InstallError('경로 탈출: %s 에 %s' % (os.path.basename(path), name))
            out = os.path.realpath(os.path.join(dest, name))
            if out != root and not out.startswith(root + os.sep):
                raise InstallError('경로 탈출: %s 에 %s' % (os.path.basename(path), name))
        archive.extractall(dest)


def _self_test(directory):
    try:
        proc = subprocess.run([sys.executable, '-c', SELF_TEST, directory],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise InstallError('self-test: %s' % exc)
    if proc.returncode != 0 or 'ok' not in proc.stdout:
        last = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ['?']
        raise InstallError('self-test: %s' % last[0])


# ---------------------------------------------------------------- the install

class _Locked:
    """One install at a time per engine dir (a SessionStart and a Stop may race)."""

    def __init__(self, base):
        self.path = os.path.join(base, 'install.lock')
        self.held = False

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        try:
            if time.time() - os.path.getmtime(self.path) > LOCK_STALE:
                os.remove(self.path)
        except OSError:
            pass
        try:
            os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            self.held = True
        except FileExistsError:
            self.held = False
        return self

    def __exit__(self, *exc):
        if self.held:
            try:
                os.remove(self.path)
            except OSError:
                pass


def installed(lock=None, interp=None, base=None):
    lock = lock or read_lock()
    target = target_dir(lock, interp, base)
    return target if os.path.isfile(os.path.join(target, 'READY')) else None


def ensure(base=None, wheels_dir=None, interp=None, lock=None, self_test=None):
    """Install if not installed. Returns the install directory; raises InstallError.

    Another install already running is not an error: the caller is told
    'installing' and the engine stays missing for this run.
    """
    lock = lock or read_lock()
    interp = interp or tags.Interpreter()
    base = base or base_dir()
    wheels_dir = wheels_dir or os.environ.get('CONVENTION_GUARD_WHEELS') or None
    done = installed(lock, interp, base)
    if done:
        return done
    try:
        chosen = choose(lock, interp)
    except InstallError as exc:
        write_status('unsupported', str(exc), base)
        raise
    target = target_dir(lock, interp, base)
    with _Locked(base) as guard:
        if not guard.held:
            raise InstallError('installing: 다른 설치가 진행 중')
        done = installed(lock, interp, base)
        if done:
            return done
        write_status('installing', '', base)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        work = tempfile.mkdtemp(prefix='.install-', dir=os.path.dirname(target))
        try:
            downloads = os.path.join(work, 'wheels')
            site = os.path.join(work, 'site')
            os.makedirs(downloads)
            os.makedirs(site)
            versions = {}
            for name, wheel in chosen.items():
                _unpack(_fetch(wheel, downloads, wheels_dir), site)
                versions[name] = wheel['filename']
            (self_test or _self_test)(site)
            with open(os.path.join(site, 'READY'), 'w', encoding='utf-8') as fh:
                json.dump({'lock': lock_id(lock), 'wheels': versions, 'at': time.time()}, fh)
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
            os.replace(site, target)
        except InstallError as exc:
            write_status('failed', str(exc), base)
            raise
        except Exception as exc:        # noqa: BLE001 -- said, not raised raw
            write_status('failed', 'internal_error:%s' % type(exc).__name__, base)
            raise InstallError('internal_error:%s: %s' % (type(exc).__name__, exc))
        finally:
            shutil.rmtree(work, ignore_errors=True)
    write_status('ok', '', base, path=target)
    return target


def kick(script):
    """Start `python3 <script> ensure --quiet` in the background, detached, if
    an install makes sense now. The caller does not wait (design §4.5)."""
    if os.environ.get('CONVENTION_GUARD_NO_ENGINE'):
        return False
    state = read_status()
    recent = time.time() - float(state.get('at') or 0) < RETRY_AFTER
    if state.get('state') == 'unsupported' or (recent and state.get('state') in
                                               ('installing', 'failed')):
        return False
    kwargs = {'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL,
              'stdin': subprocess.DEVNULL}
    if os.name == 'nt':
        kwargs['creationflags'] = 0x00000008 | 0x00000200   # DETACHED | NEW_PROCESS_GROUP
    else:
        kwargs['start_new_session'] = True
    try:
        subprocess.Popen([sys.executable, script, 'ensure', '--quiet'], **kwargs)
    except OSError:
        return False
    write_status('installing', 'background', **{})
    return True


# ---------------------------------------------------------------- the lock file

def build_lock(pins=PINS):
    """lock.json from the PyPI JSON API: every CPython wheel of each pinned version."""
    import urllib.request
    packages = []
    for name, version, module in pins:
        url = 'https://pypi.org/pypi/%s/%s/json' % (name, version)
        with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT) as resp:
            data = json.load(resp)
        files = []
        for item in data.get('urls') or []:
            filename = item.get('filename', '')
            if item.get('packagetype') != 'bdist_wheel' or item.get('yanked'):
                continue
            try:
                _n, _v, pythons, _abis, _plats = tags.parse(filename)
            except ValueError:
                continue
            if not any(p.startswith('cp3') for p in pythons):
                continue
            files.append({'filename': filename, 'url': item['url'],
                          'sha256': item['digests']['sha256'], 'size': item.get('size')})
        if not files:
            raise InstallError('%s==%s 에 휠이 없음' % (name, version))
        packages.append({'name': name, 'version': version, 'module': module,
                         'files': sorted(files, key=lambda f: f['filename'])})
    return {'comment': 'scripts/engine.py lock 이 만든 파일입니다. 손으로 고치지 마세요.',
            'packages': packages}


def verify_lock(lock=None):
    """[problem] for every wheel PyPI no longer serves as the lock says."""
    lock = lock or read_lock()
    fresh = {(p['name'], p['version']): {f['filename']: f['sha256'] for f in p['files']}
             for p in build_lock([(p['name'], p['version'], p['module'])
                                  for p in lock['packages']])['packages']}
    problems = []
    for package in lock['packages']:
        served = fresh.get((package['name'], package['version']), {})
        for wheel in package['files']:
            if served.get(wheel['filename']) != wheel['sha256']:
                problems.append('%s: PyPI 와 다름' % wheel['filename'])
    return problems
