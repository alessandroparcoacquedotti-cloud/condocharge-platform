from __future__ import annotations


class IntegrationError(Exception):
    pass


class DriverNotSupportedError(IntegrationError):
    pass


class StationUnreachableError(IntegrationError):
    pass
