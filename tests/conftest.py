from __future__ import annotations

import pytest

from core.config.settings import Settings, get_settings


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return Settings()
