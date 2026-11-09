"""Preview scoped JoyBoyz retention; pass --apply to remove eligible items."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BACKUPS = ROOT.parent / 'backups/tcgradar'
STATE = BACKUPS / 'deployments'
REPOSITORY = 'joyboyz-tcg-radar'
PROJECT = 'joyboyz-tcg-radar'
KEEP_IMAGES = 5
KEEP_BACKUPS = 10
KEEP_RECORDS = 10
KEEP_DAYS = 30
STAMP = re.compile(r'\d{8}T\d{6}(?:\d{6})?Z')


def docker(*args):
    result = subprocess.run(['docker', *args], text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('Docker inventory or cleanup failed: ' + args[0])
    return result.stdout.strip()


def stamp_time(name):
    if not STAMP.fullmatch(name):
        raise ValueError('Not a managed timestamp')
    pattern = '%Y%m%dT%H%M%S%fZ' if len(name) == 22 else '%Y%m%dT%H%M%SZ'
    return datetime.strptime(name, pattern).replace(tzinfo=timezone.utc)


def checked_child(path, parent):
    """Deletion is limited to real direct children, with no nested symlinks."""
    parent, path = Path(parent), Path(path)
    if parent.is_symlink() or path.is_symlink() or path.resolve().parent != parent.resolve():
        raise RuntimeError('Refusing cleanup outside the expected directory')
    if any(item.is_symlink() for item in path.rglob('*')):
        raise RuntimeError('Refusing cleanup of a directory containing symlinks')
    return path


def expired_directories(paths, protected, now, keep):
    ordered = sorted(paths, key=lambda path: stamp_time(path.name), reverse=True)
    retained = set(ordered[:keep]) | set(protected)
    return [path for path in ordered if path not in retained and stamp_time(path.name) < now - timedelta(days=KEEP_DAYS)]


def own_tags(image):
    return [tag for tag in image.get('RepoTags') or [] if tag.startswith(REPOSITORY + ':')]


def image_candidates(images, protected_ids):
    ordered = sorted((image for image in images if own_tags(image)), key=lambda image: image['Created'], reverse=True)
    keep = set(protected_ids) | {image['Id'] for image in ordered[:KEEP_IMAGES]}
    return [image for image in ordered if image['Id'] not in keep]


def disposable_container(container, current_services):
    labels = container['Config'].get('Labels') or {}
    service = labels.get('com.docker.compose.service')
    state = container['State']
    return (labels.get('com.docker.compose.project') == PROJECT
            and service in ('worker', 'migrate') and service not in current_services
            and state['Status'] == 'exited' and state['ExitCode'] == 0
            and all(not mount.get('RW') and mount.get('Type') != 'volume' for mount in container.get('Mounts', [])))


def containers():
    ids = docker('ps', '-aq').splitlines()
    return json.loads(docker('inspect', *ids)) if ids else []


def read_reference(path):
    path = Path(path)
    checked_child(path.parent, STATE)
    if path.name != 'previous.json' or path.is_symlink():
        raise RuntimeError('Invalid rollback metadata reference')
    return json.loads(path.read_text())


def protected_state():
    # Fail closed if the active release cannot be identified.
    current = json.loads((STATE / 'current.json').read_text())
    references = [current]
    protected_records = set()
    if current.get('previous'):
        references.append(read_reference(current['previous']))
        protected_records.add(Path(current['previous']).parent)
    for path in STATE.iterdir():
        release = path / 'release.json'
        if path.is_dir() and not path.is_symlink() and STAMP.fullmatch(path.name) and release.is_file():
            if json.loads(release.read_text()).get('commit') == current['commit']:
                protected_records.add(path)
    protected_ids = set()
    for reference in references:
        image = reference['image']
        if not image.startswith(REPOSITORY + ':'):
            raise RuntimeError('Active release image is outside the JoyBoyz repository')
        protected_ids.add(json.loads(docker('image', 'inspect', image))[0]['Id'])
    protected_backups = set()
    for reference in references:
        if reference.get('backup'):
            protected_backups.add(checked_child(Path(reference['backup']), BACKUPS))
    return current, protected_ids, protected_records, protected_backups


def complete_backup(path):
    if not path.is_dir() or path.is_symlink() or not STAMP.fullmatch(path.name):
        return False
    if not all((path / name).is_file() for name in ('radar.dump', '.env', 'compose.yaml', 'config/shops.json')):
        return False
    with (path / 'radar.dump').open('rb') as stream:
        return stream.read(5) == b'PGDMP'


def make_plan(now=None):
    now = now or datetime.now(timezone.utc)
    current, protected_ids, protected_records, protected_backups = protected_state()
    inventory = containers()
    retired = [container for container in inventory if disposable_container(container, current['services'])]
    retired_ids = {container['Id'] for container in retired}
    protected_ids.update(container['Image'] for container in inventory if container['Id'] not in retired_ids)
    ids = sorted(set(docker('image', 'ls', '--filter', 'reference=' + REPOSITORY + ':*', '--quiet', '--no-trunc').splitlines()))
    images = json.loads(docker('image', 'inspect', *ids)) if ids else []
    backups = [path for path in BACKUPS.iterdir() if complete_backup(path)]
    records = [path for path in STATE.iterdir() if path.is_dir() and not path.is_symlink() and STAMP.fullmatch(path.name)]
    expired_records = expired_directories(records, protected_records, now, KEEP_RECORDS)
    # Retained audit records may reference older pre-migration backups.
    for path in set(records) - set(expired_records):
        for name in ('release.json', 'previous.json'):
            metadata = path / name
            if metadata.is_file():
                reference = json.loads(metadata.read_text())
                if reference.get('backup'):
                    protected_backups.add(checked_child(Path(reference['backup']), BACKUPS))
    return {
        'containers': retired,
        'images': image_candidates(images, protected_ids),
        'backups': expired_directories(backups, protected_backups, now, KEEP_BACKUPS),
        'records': expired_records,
    }


def apply_plan(plan):
    removed, skipped = [], []
    for container in plan['containers']:
        try:
            latest = json.loads(docker('inspect', container['Id']))[0]
            current = json.loads((STATE / 'current.json').read_text())
            if not disposable_container(latest, current['services']):
                raise RuntimeError('Container state changed')
            docker('rm', container['Id'])
            removed.append(container['Name'].lstrip('/'))
        except RuntimeError:
            skipped.append(container['Name'].lstrip('/'))
    for image in plan['images']:
        # Recheck all containers; never force deletion or prune globally.
        if image['Id'] in {container['Image'] for container in containers()}:
            skipped.extend(own_tags(image))
            continue
        for tag in own_tags(image):
            try:
                actual = json.loads(docker('image', 'inspect', tag))[0]['Id']
                if actual != image['Id']:
                    raise RuntimeError('Image tag changed')
                docker('image', 'rm', tag)
                removed.append(tag)
            except RuntimeError:
                skipped.append(tag)
    for key, parent in (('backups', BACKUPS), ('records', STATE)):
        for path in plan[key]:
            checked_child(path, parent)
            stamp_time(path.name)
            if key == 'backups' and not complete_backup(path):
                raise RuntimeError('Backup changed since preview')
            shutil.rmtree(path)
            removed.append(str(path))
    return {'removed': removed, 'skipped': skipped}


@contextmanager
def maintenance_lock():
    import fcntl
    with (STATE / 'deploy.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    with maintenance_lock() as acquired:
        if not acquired:
            print('Cleanup skipped: a deployment or another cleanup is running.')
            return
        plan = make_plan()
        preview = {'containers': [container['Name'].lstrip('/') for container in plan['containers']],
                   'images': [tag for image in plan['images'] for tag in own_tags(image)],
                   'backups': [str(path) for path in plan['backups']], 'records': [str(path) for path in plan['records']]}
        print(json.dumps({'mode': 'apply' if args.apply else 'preview', **preview}), flush=True)
        if args.apply:
            print(json.dumps(apply_plan(plan)), flush=True)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError) as error:
        raise SystemExit(str(error)) from None
