"""Back up the running PostgreSQL database and deployment configuration privately."""
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    destination = Path(os.environ.get("RADAR_BACKUP_DIR", root.parent / "backups" / "tcgradar"))
    os.umask(0o077)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    temporary = Path(tempfile.mkdtemp(prefix=".pending-", dir=destination))
    try:
        with (temporary / "radar.dump").open("wb") as dump:
            subprocess.run(
                ["docker", "compose", "exec", "-T", "db", "pg_dump", "-U", "radar", "-d", "radar", "-Fc"],
                cwd=root, stdout=dump, check=True,
            )
        for relative in (".env", "config/shops.json", "compose.yaml", "compose.traefik.yaml", "compose.workers.yaml"):
            if relative == 'compose.workers.yaml' and not (root / relative).exists():
                continue
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / relative, target)
        final = destination / stamp
        temporary.rename(final)
        print(f"Backup complete: {final}")
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


if __name__ == "__main__":
    main()
