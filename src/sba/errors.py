"""Exception hierarchy. Every domain error derives from SBAError."""


class SBAError(Exception):
    """Base class for all Stock Behaviour Analyzer errors."""


class ConfigError(SBAError):
    """Configuration is missing, malformed or inconsistent."""


class DataFetchError(SBAError):
    """A data provider failed or returned unusable data."""


class StorageError(SBAError):
    """A storage backend failed to read or write."""


class FeatureError(SBAError):
    """Feature computation received unusable input."""
