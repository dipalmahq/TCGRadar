"""Create an initial .env with private random credentials. Never overwrites one."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
target = root / ".env"
if target.exists():
    raise SystemExit(".env already exists; nothing changed.")
content = (root / ".env.example").read_text(encoding="utf-8")
content = content.replace("GENERATE_A_RANDOM_DATABASE_PASSWORD", secrets.token_hex(24))
content = content.replace("GENERATE_A_RANDOM_TEAM_KEY", secrets.token_urlsafe(36))
with target.open("x", encoding="utf-8") as file:
    file.write(content)
print("Created .env with random credentials. Keep it private. No credentials were printed.")
