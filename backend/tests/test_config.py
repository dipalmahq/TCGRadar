import pytest
from pydantic import ValidationError
from app.config import Settings


def test_production_refuses_missing_or_short_shared_key():
    for key in ("", "short-key"):
        with pytest.raises(ValidationError, match="at least 32"):
            Settings(_env_file=None, environment="production", api_key=key)
    assert Settings(_env_file=None, environment="production", api_key="x" * 40).api_key
