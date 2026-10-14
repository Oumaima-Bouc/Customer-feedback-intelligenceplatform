"""
Shared Config Library — Consul-backed distributed configuration.

Provides:
  - ConfigManager: watches Consul KV, validates, applies hot-reload / signals restart
  - Schema definitions (Pydantic) for all service configs
  - Validation + versioning
  - Reload / restart handler registries

Every service imports this library and instantiates its own ConfigManager.
"""
from shared.config_lib.manager import ConfigManager
from shared.config_lib.schema import (
    GlobalConfig,
    AIServiceAConfig,
    AIServiceBConfig,
    ConfigEnvelope,
)
from shared.config_lib.validator import validate_config

__all__ = [
    "ConfigManager",
    "GlobalConfig",
    "AIServiceAConfig",
    "AIServiceBConfig",
    "ConfigEnvelope",
    "validate_config",
]
