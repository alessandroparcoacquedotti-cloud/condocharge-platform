from __future__ import annotations

from collections.abc import Iterator

import pytest

from condocharge.core.config import get_settings
from condocharge.core.rate_limit import reset_rate_limit_state


@pytest.fixture(autouse=True)
def _reset_cached_runtime_state() -> Iterator[None]:
    get_settings.cache_clear()
    reset_rate_limit_state()
    yield
    get_settings.cache_clear()
    reset_rate_limit_state()
