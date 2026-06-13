from __future__ import annotations

from condocharge.app.integrations.drivers.registry import DriverRegistry
from condocharge.app.integrations.legrand.driver import as_driver as legrand_driver
from condocharge.app.integrations.base.models import StationVendor


def create_default_registry() -> DriverRegistry:
    registry = DriverRegistry()
    registry.register(StationVendor.LEGRAND_GREENUP, legrand_driver)
    return registry
