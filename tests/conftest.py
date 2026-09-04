from __future__ import annotations

import os

import pytest

from core.config.settings import ExecutionMode, Settings, get_settings


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    os.environ["EXECUTION_MODE"] = "DRY_RUN"
    s = Settings()
    assert s.execution_mode == ExecutionMode.DRY_RUN
    return s
