from __future__ import annotations

from collections.abc import Callable

from condocharge.app.integrations.base.driver import StationDriver
from condocharge.app.integrations.base.errors import DriverNotSupportedError
from condocharge.app.integrations.base.models import StationTarget, StationVendor

DriverFactory = Callable[[], StationDriver]


class DriverRegistry:
    def __init__(self) -> None:
        self._factories: dict[StationVendor, DriverFactory] = {}

    def register(self, vendor: StationVendor, factory: DriverFactory) -> None:
        self._factories[vendor] = factory

    def create_driver(self, target: StationTarget) -> StationDriver:
        factory = self._factories.get(target.vendor)
        if factory is None:
            raise DriverNotSupportedError(f"No driver registered for vendor={target.vendor}")
        driver = factory()
        if not driver.supports(target):
            raise DriverNotSupportedError(f"Driver does not support station target vendor={target.vendor}")
        return driver

