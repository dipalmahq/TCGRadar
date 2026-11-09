#!/usr/bin/python3
"""Install as ~/.local/bin/joyboyz-deploy-ssh; use only as an SSH forced command."""
import os
from pathlib import Path
import re
import subprocess
import sys

root = Path.home() / 'dipalmaHQ/TCGRadar'
match = re.fullmatch(r'deploy ([0-9a-f]{40})', os.environ.get('SSH_ORIGINAL_COMMAND', ''))
if not match:
    raise SystemExit('This key permits only: deploy <full-main-commit-sha>')
commit = match.group(1)


def git(*args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


git('fetch', 'origin', 'main')
if git('rev-parse', 'origin/main') != commit:
    print('Skipped superseded commit; a newer main commit will deploy.')
    raise SystemExit(0)
# Read the approved main script without modifying the running checkout. This also
# works after rolling back to a release predating the deployment scripts.
script = root / 'scripts/deploy.py'
source = git('show', commit + ':scripts/deploy.py')
sys.argv = [str(script), '--ssh']
exec(compile(source, str(script), 'exec'), {'__name__': '__main__', '__file__': str(script)})
