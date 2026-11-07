"""Host-side container checks using native Docker or existing Ubuntu/WSL Docker.

    python scripts/container_check.py           # Read-only deployment checks
    python scripts/container_check.py --discord # Send one explicit test alarm

Credentials are only read inside the existing container, never shell arguments.
"""
import argparse
from pathlib import Path
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser()
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--discord", action="store_true", help="Explicitly send one Discord test alarm")
    actions.add_argument("--quality", action="store_true", help="Read-only live product sample audit")
    actions.add_argument("--masters", action="store_true", help="Read-only Masters integration check")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    docker = shutil.which("docker")
    if docker:
        command = [docker]
    elif shutil.which("wsl"):
        linux_root = subprocess.check_output(["wsl", "-d", "Ubuntu", "--exec", "wslpath", "-a", "-u", str(root)], text=True).strip()
        if not linux_root.startswith("/"):
            raise SystemExit("Unable to resolve project path in Ubuntu/WSL")
        command = ["wsl", "-d", "Ubuntu", "-u", "root", "--cd", linux_root, "--exec", "docker"]
    else:
        raise SystemExit("Docker or the configured Ubuntu/WSL runtime is required")
    script = root / "scripts" / ("test_discord.py" if args.discord else "audit_quality.py" if args.quality else "verify_masters.py" if args.masters else "check_deployment.py")
    result = subprocess.run(command + ["compose", "exec", "-T", "api", "python", "-"], input=script.read_bytes(), cwd=root)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
