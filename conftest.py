"""Tests never see the developer's configuration: neither ``.env`` nor the variables LiteLLM loads
from it into the process environment (it calls ``load_dotenv`` on import). Settings come from their
defaults and from what each test passes or sets itself."""

import pytest
from ircb.settings import Settings

Settings.model_config["env_file"] = None


@pytest.fixture(autouse=True)
def _no_developer_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, field in Settings.model_fields.items():
        aliases = getattr(field.validation_alias, "choices", [])
        for env in (name.upper(), *(str(a).upper() for a in aliases)):
            monkeypatch.delenv(env, raising=False)
