"""Deployment guards must protect credentials and prevent unsafe rollbacks."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = next(path for path in (Path(__file__).resolve().parents[2] / 'scripts/deploy.py', Path('/app/scripts/deploy.py')) if path.exists())
spec = importlib.util.spec_from_file_location('radar_deployment', SCRIPT)
deployment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployment)


def test_deploy_key_rejects_shell_commands_and_unpinned_references():
    commit = 'a' * 40
    assert deployment.ssh_commit('deploy ' + commit) == commit
    for command in ('', 'bash', 'deploy main', 'rollback ' + commit, 'deploy ' + commit + '; id', 'deploy ' + commit + ' extra'):
        with pytest.raises(ValueError):
            deployment.ssh_commit(command)


def test_managed_image_does_not_change_private_settings_or_duplicate_keys():
    original = '# Private\r\nRADAR_API_KEY=keep-secret\r\nRADAR_IMAGE=old\r\nexport RADAR_IMAGE=duplicate\r\nPOSTGRES_PASSWORD=keep-password\r\n'
    updated = deployment.image_environment(original, 'joyboyz-tcg-radar:' + 'b' * 40)
    assert updated.count('RADAR_IMAGE=') == 1
    assert 'RADAR_API_KEY=keep-secret\n' in updated
    assert 'POSTGRES_PASSWORD=keep-password\n' in updated
    assert updated.startswith('# Private\n')


def test_schema_change_blocks_restore_before_any_config_or_service_mutation(monkeypatch):
    monkeypatch.setattr(deployment, 'schema', lambda: 'new-schema')
    monkeypatch.setattr(deployment, 'atomic_write', lambda *a: pytest.fail('Must not restore config across schema changes'))
    monkeypatch.setattr(deployment, 'run', lambda *a, **k: pytest.fail('Must not start old code across schema changes'))
    with pytest.raises(RuntimeError, match='Schema changed'):
        deployment.restore({'schema': 'old-schema'})


def test_failed_build_restores_checkout_without_stopping_current_release(tmp_path, monkeypatch):
    root = tmp_path / 'app'
    root.mkdir()
    (root / '.env').write_text('RADAR_API_KEY=keep-secret\n')
    state = tmp_path / 'state'
    state.mkdir()
    monkeypatch.setattr(deployment, 'ROOT', root)
    monkeypatch.setattr(deployment, 'STATE', state)
    old_commit, new_commit = 'a' * 40, 'b' * 40
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(args)
        if args == ('git', 'rev-parse', 'origin/main'):
            return new_commit
        if args == ('git', 'rev-parse', 'HEAD'):
            return old_commit
        if args[:2] == ('docker', 'inspect'):
            return 'old-image-id'
        return ''

    def fake_compose(*args, **kwargs):
        calls.append(('compose', *args))
        if args[0] == 'build':
            raise RuntimeError('Build failed')
        return 'container'

    monkeypatch.setattr(deployment, 'run', fake_run)
    monkeypatch.setattr(deployment, 'compose', fake_compose)
    monkeypatch.setattr(deployment, 'services', lambda: ['api', 'notifications'])
    monkeypatch.setattr(deployment, 'schema', lambda: 'schema')
    with pytest.raises(RuntimeError, match='Build failed'):
        deployment.deploy(new_commit)
    assert ('git', 'checkout', '--detach', old_commit) in calls
    assert not any(call[:2] == ('compose', 'stop') for call in calls)
    assert (root / '.env').read_text() == 'RADAR_API_KEY=keep-secret\n'


def test_restore_stops_new_services_and_restarts_previous_image(tmp_path, monkeypatch):
    monkeypatch.setattr(deployment, 'ROOT', tmp_path)
    monkeypatch.setattr(deployment, 'schema', lambda: 'unchanged-schema')
    monkeypatch.setattr(deployment, 'services', lambda: ['api', 'worker-new-shop'])
    calls = []
    monkeypatch.setattr(deployment, 'run', lambda *a, **k: calls.append(('run', a, k)))
    monkeypatch.setattr(deployment, 'compose', lambda *a, **k: calls.append(('compose', a, k)))
    previous = {'schema': 'unchanged-schema', 'commit': 'a' * 40, 'image': 'joyboyz-tcg-radar:previous',
                'environment': 'RADAR_API_KEY=preserved\n', 'services': ['api', 'worker-old-shop']}
    deployment.restore(previous)
    assert calls[0] == ('compose', ('stop', 'api', 'worker-new-shop'), {})
    assert ('run', ('git', 'checkout', '--detach', 'a' * 40), {}) in calls
    assert calls[-1][2]['image'] == previous['image']
    assert calls[-1][1][-2:] == ('api', 'worker-old-shop')
    restored = (tmp_path / '.env').read_text()
    assert 'RADAR_API_KEY=preserved\n' in restored
    assert 'RADAR_IMAGE=joyboyz-tcg-radar:previous\n' in restored
