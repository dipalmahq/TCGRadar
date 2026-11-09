"""Deploy a tested main commit over SSH; keep private release state outside Git."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT.parent / 'backups/tcgradar/deployments'
SHA = re.compile(r'[0-9a-f]{40}')


def run(*args, env=None):
    result = subprocess.run(args, cwd=ROOT, env=env, text=True, capture_output=True)
    if result.returncode:
        # Compose config and application exceptions can contain credentials.
        raise RuntimeError(f'Command failed ({result.returncode}): {args[0]} {args[1]}')
    return result.stdout.strip()


def compose(*args, image=None):
    env = dict(os.environ)
    if image:
        env['RADAR_IMAGE'] = image
    return run('docker', 'compose', *args, env=env)


def atomic_write(path, content):
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8', newline='\n') as stream:
        stream.write(content)
    temporary.chmod(0o600)
    temporary.replace(path)


def image_environment(content, image):
    """Preserve private settings while replacing exactly the managed image value."""
    lines = [line for line in content.splitlines() if not re.match(r'^\s*(?:export\s+)?RADAR_IMAGE\s*=', line)]
    return '\n'.join(lines) + '\nRADAR_IMAGE=' + image + '\n'


def services():
    config = json.loads(compose('config', '--format', 'json'))
    return [name for name in config['services'] if name in ('api', 'notifications') or name.startswith('worker-')]


def schema():
    return compose('exec', '-T', 'db', 'psql', '-U', 'radar', '-d', 'radar', '-Atc', 'SELECT version_num FROM alembic_version')


def require_same_schema(expected, actual):
    if expected != actual:
        raise RuntimeError('Schema changed: automatic image rollback is unsafe. Use the private backup and repair forward or explicitly restore the database.')


def http_status(path):
    try:
        with urllib.request.urlopen('https://radar.joyboyz.de' + path, timeout=15) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def verify(commit, apps):
    container = compose('ps', '-q', 'api')
    revision = run('docker', 'inspect', '--format', '{{index .Config.Labels "org.opencontainers.image.revision"}}', container)
    if revision != commit:
        raise RuntimeError('Running API revision differs from requested commit')
    rows = compose('ps', '--format', 'json').splitlines()
    running = {row['Service'] for line in rows if (row := json.loads(line))['State'] == 'running'}
    if not set(apps).issubset(running):
        raise RuntimeError('Some application services are not running')
    # The key stays inside the container, never in arguments or logs.
    code = 'from app.config import get_settings; import urllib.request; s=get_settings(); r=urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8000/api/meta",headers={"X-Radar-Key":s.api_key}),timeout=10); assert r.status==200; print("Team authentication verified")'
    compose('exec', '-T', 'api', 'python', '-c', code)
    for attempt in range(6):
        try:
            if all(http_status(path) == expected for path, expected in (('/', 200), ('/api/health', 200), ('/api/offers', 401))):
                return
        except OSError:
            pass
        if attempt < 5:
            time.sleep(2)
    raise RuntimeError('Public dashboard, health or authentication check failed')


@contextmanager
def deployment_lock():
    import fcntl
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE / 'deploy.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another deployment is already running') from None
        yield


def restore(previous):
    # Check before restoring config, source or starting old application code.
    require_same_schema(previous['schema'], schema())
    compose('stop', *services())
    atomic_write(ROOT / '.env', image_environment(previous['environment'], previous['image']))
    run('git', 'checkout', '--detach', previous['commit'])
    compose('up', '-d', '--no-deps', '--no-build', '--wait', '--wait-timeout', '150', *previous['services'], image=previous['image'])


def deploy(commit):
    if run('git', 'status', '--porcelain'):
        raise RuntimeError('Server checkout is dirty; save and reconcile changes before deployment')
    run('git', 'fetch', 'origin', 'main')
    if run('git', 'rev-parse', 'origin/main') != commit:
        print('Skipped superseded commit; only the current main head can deploy.', flush=True)
        return
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    attempt = STATE / stamp
    attempt.mkdir(mode=0o700)
    container = compose('ps', '-q', 'api')
    old_image_id = run('docker', 'inspect', '--format', '{{.Image}}', container)
    previous_image = 'joyboyz-tcg-radar:before-' + stamp.lower()
    run('docker', 'tag', old_image_id, previous_image)
    previous = {'commit': run('git', 'rev-parse', 'HEAD'), 'schema': schema(),
                'image': previous_image, 'environment': (ROOT / '.env').read_text(), 'services': services()}
    if (STATE / 'current.json').exists():
        previous['backup'] = json.loads((STATE / 'current.json').read_text()).get('backup')
    atomic_write(attempt / 'previous.json', json.dumps(previous, indent=2))
    backup_output = run(sys.executable, 'scripts/backup.py')
    print(backup_output, flush=True)
    backup = backup_output.removeprefix('Backup complete: ').strip()
    image = 'joyboyz-tcg-radar:' + commit
    switched = False
    try:
        run('git', 'checkout', '--detach', commit)
        run(sys.executable, 'scripts/generate_merchant_workers.py')
        if run('git', 'status', '--porcelain'):
            raise RuntimeError('Generated worker configuration must be committed before deployment')
        compose('config', '--quiet', image=image)
        print('Building image for ' + commit, flush=True)
        compose('build', '--build-arg', 'VCS_REF=' + commit, 'api', image=image)
        apps = services()
        compose('stop', *previous['services'])
        switched = True
        atomic_write(ROOT / '.env', image_environment(previous['environment'], image))
        print('Applying migrations with application services stopped', flush=True)
        compose('run', '--rm', '--no-deps', 'migrate', image=image)
        compose('up', '-d', '--no-deps', '--no-build', '--wait', '--wait-timeout', '150', *apps, image=image)
        verify(commit, apps)
        release = {'commit': commit, 'image': image, 'schema': schema(), 'services': apps, 'backup': backup,
                   'deployed_at': stamp, 'previous': str(attempt / 'previous.json')}
        atomic_write(attempt / 'release.json', json.dumps(release, indent=2))
        atomic_write(STATE / 'current.json', json.dumps(release, indent=2))
        print(json.dumps({'status': 'deployed', **release}), flush=True)
    except Exception:
        if switched:
            try:
                restore(previous)
                print('Deployment failed; previous image and source restored.', flush=True)
            except Exception as recovery_error:
                # Avoid leaving the new code running after an unsuccessful verification.
                compose('stop', *services())
                raise RuntimeError(f'Deployment failed and needs recovery. {recovery_error}. Backup metadata: {attempt}') from None
        else:
            # Build/config failures never stop the running release.
            run('git', 'restore', '--', 'compose.workers.yaml')
            run('git', 'checkout', '--detach', previous['commit'])
        raise


def rollback():
    if run('git', 'status', '--porcelain'):
        raise RuntimeError('Server checkout is dirty; reconcile changes first')
    current = json.loads((STATE / 'current.json').read_text())
    if 'previous' not in current:
        raise RuntimeError('No earlier managed release is available; the previous release was already restored')
    previous = json.loads(Path(current['previous']).read_text())
    require_same_schema(previous['schema'], schema())
    restore(previous)
    if http_status('/api/health') != 200 or http_status('/') != 200:
        raise RuntimeError('Previous release did not pass public health checks')
    restored = {key: value for key, value in previous.items() if key != 'environment'}
    restored['rolled_back_at'] = datetime.now(timezone.utc).isoformat()
    atomic_write(STATE / 'current.json', json.dumps(restored, indent=2))
    print(json.dumps({'status': 'rolled_back', **restored}), flush=True)


def ssh_commit(command):
    parts = shlex.split(command)
    if len(parts) != 2 or parts[0] != 'deploy' or not SHA.fullmatch(parts[1]):
        raise ValueError('SSH key permits only: deploy <full-main-commit-sha>')
    return parts[1]


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', choices=('deploy', 'rollback', 'status'))
    parser.add_argument('commit', nargs='?')
    parser.add_argument('--ssh', action='store_true')
    args = parser.parse_args()
    if args.ssh:
        args.action, args.commit = 'deploy', ssh_commit(os.environ.get('SSH_ORIGINAL_COMMAND', ''))
    if args.action == 'deploy' and not SHA.fullmatch(args.commit or ''):
        parser.error('deploy requires a full lowercase commit SHA')
    if args.action == 'status':
        print((STATE / 'current.json').read_text())
        return
    if args.action not in ('deploy', 'rollback'):
        parser.error('choose deploy, rollback or status')
    with deployment_lock():
        deploy(args.commit) if args.action == 'deploy' else rollback()


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
