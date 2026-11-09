"""Retention must preserve live/rollback data and stay within the project scope."""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = next(path for path in (Path(__file__).resolve().parents[2] / 'scripts/cleanup.py', Path('/app/scripts/cleanup.py')) if path.exists())
spec = importlib.util.spec_from_file_location('radar_cleanup', SCRIPT)
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)


def test_images_keep_five_recent_versions_and_old_in_use_or_rollback_images():
    images = [{'Id': str(i), 'Created': f'2026-01-{i + 1:02}T00:00:00Z',
               'RepoTags': [f'joyboyz-tcg-radar:release-{i}']} for i in range(8)]
    images.append({'Id': 'other', 'Created': '2099-01-01T00:00:00Z', 'RepoTags': ['other-app:latest']})
    candidates = cleanup.image_candidates(images, {'0', '1'})
    assert [image['Id'] for image in candidates] == ['2']
    assert cleanup.own_tags({'RepoTags': ['joyboyz-tcg-radar:old', 'other-app:latest']}) == ['joyboyz-tcg-radar:old']


def test_backups_keep_thirty_days_ten_newest_and_explicit_recovery_reference(tmp_path):
    paths = [tmp_path / f'202601{day:02}T041500000000Z' for day in range(1, 13)]
    paths.append(tmp_path / '20261108T041500000000Z')
    expired = cleanup.expired_directories(paths, {paths[0]}, datetime(2026, 11, 9, tzinfo=timezone.utc), 10)
    assert set(expired) == {paths[1], paths[2]}
    assert not cleanup.expired_directories(paths, set(), datetime(2026, 1, 15, tzinfo=timezone.utc), 10)


def test_only_complete_timestamped_database_backups_are_managed(tmp_path):
    path = tmp_path / '20260101T041500000000Z'
    path.mkdir()
    (path / 'radar.dump').write_bytes(b'PGDMParchive')
    (path / '.env').write_text('private')
    (path / 'compose.yaml').write_text('services: {}')
    assert not cleanup.complete_backup(path)
    (path / 'config').mkdir()
    (path / 'config/shops.json').write_text('[]')
    assert cleanup.complete_backup(path)
    (path / 'radar.dump').write_bytes(b'not-a-postgres-dump')
    assert not cleanup.complete_backup(path)


def test_cleanup_rejects_outside_paths_and_symlinks(tmp_path):
    parent = tmp_path / 'managed'
    parent.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    with pytest.raises(RuntimeError, match='outside'):
        cleanup.checked_child(outside, parent)
    link = parent / 'linked'
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('Creating symlinks needs an additional Windows privilege')
    with pytest.raises(RuntimeError, match='outside'):
        cleanup.checked_child(link, parent)


def legacy_container(**changes):
    value = {'Id': 'container', 'Name': '/old-worker', 'Image': 'old-image',
             'Config': {'Labels': {'com.docker.compose.project': 'joyboyz-tcg-radar', 'com.docker.compose.service': 'worker'}},
             'State': {'Status': 'exited', 'ExitCode': 0}, 'Mounts': [{'Type': 'bind', 'RW': False}]}
    value.update(changes)
    return value


def test_retired_container_cleanup_never_removes_live_services_or_data_volumes():
    assert cleanup.disposable_container(legacy_container(), ['api'])
    assert not cleanup.disposable_container(legacy_container(), ['api', 'worker'])
    assert not cleanup.disposable_container(legacy_container(State={'Status': 'running', 'ExitCode': 0}), [])
    assert not cleanup.disposable_container(legacy_container(State={'Status': 'exited', 'ExitCode': 1}), [])
    assert not cleanup.disposable_container(legacy_container(Mounts=[{'Type': 'volume', 'RW': False}]), [])
    assert not cleanup.disposable_container(legacy_container(Mounts=[{'Type': 'bind', 'RW': True}]), [])
    other = legacy_container(Config={'Labels': {'com.docker.compose.project': 'other-app', 'com.docker.compose.service': 'worker'}})
    assert not cleanup.disposable_container(other, [])


def test_active_and_rollback_images_and_backups_are_pinned(tmp_path, monkeypatch):
    state = tmp_path / 'deployments'
    state.mkdir()
    attempt = state / '20260101T000000000000Z'
    attempt.mkdir()
    previous = attempt / 'previous.json'
    backup = tmp_path / '20260101T000001000000Z'
    backup.mkdir()
    previous.write_text(json.dumps({'image': 'joyboyz-tcg-radar:old', 'backup': str(backup)}))
    (state / 'current.json').write_text(json.dumps({'commit': 'current', 'image': 'joyboyz-tcg-radar:current', 'previous': str(previous)}))
    monkeypatch.setattr(cleanup, 'STATE', state)
    monkeypatch.setattr(cleanup, 'BACKUPS', tmp_path)
    monkeypatch.setattr(cleanup, 'docker', lambda *args: json.dumps([{'Id': args[-1]}]))
    _, ids, records, backups = cleanup.protected_state()
    assert ids == {'joyboyz-tcg-radar:old', 'joyboyz-tcg-radar:current'}
    assert attempt in records and backup in backups


def test_image_acquired_by_a_container_after_preview_is_not_removed(monkeypatch):
    monkeypatch.setattr(cleanup, 'containers', lambda: [{'Image': 'now-in-use'}])
    monkeypatch.setattr(cleanup, 'docker', lambda *args: pytest.fail('In-use image must not be removed'))
    plan = {'containers': [], 'images': [{'Id': 'now-in-use', 'RepoTags': ['joyboyz-tcg-radar:old']}], 'backups': [], 'records': []}
    result = cleanup.apply_plan(plan)
    assert result == {'removed': [], 'skipped': ['joyboyz-tcg-radar:old']}
