"""
reload_handlers.py — Registry for hot-reload callbacks.

When a HOT-RELOADABLE config key changes, the registered handler is called
to apply the new value in-memory WITHOUT restarting the process.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# type alias: handler(key_path, old_value, new_value) -> None
ReloadHandler = Callable[[str, Any, Any], None]


class ReloadHandlerRegistry:
    """
    Services register handlers for specific config key paths.
    When a hot-reload event fires, matching handlers are invoked.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[ReloadHandler]] = {}
        self._global_handlers: list[ReloadHandler] = []

    def register(self, key_path: str, handler: ReloadHandler) -> None:
        """Register a handler for a specific dotted key path."""
        self._handlers.setdefault(key_path, []).append(handler)
        logger.debug("reload_handler.registered", extra={"key": key_path})

    def register_global(self, handler: ReloadHandler) -> None:
        """Register a handler that fires on ANY config change."""
        self._global_handlers.append(handler)

    def fire(self, changed_keys: dict[str, tuple[Any, Any]]) -> int:
        """
        Fire handlers for all changed keys.

        Args:
            changed_keys: {key_path: (old_value, new_value)}

        Returns:
            Number of handlers successfully invoked.
        """
        invoked = 0
        for key_path, (old_val, new_val) in changed_keys.items():
            handlers = self._handlers.get(key_path, [])
            for h in handlers:
                try:
                    h(key_path, old_val, new_val)
                    invoked += 1
                except Exception as exc:
                    logger.error(
                        "reload_handler.failed",
                        extra={"key": key_path, "error": str(exc)},
                    )

            for h in self._global_handlers:
                try:
                    h(key_path, old_val, new_val)
                    invoked += 1
                except Exception as exc:
                    logger.error(
                        "reload_handler.global_failed",
                        extra={"key": key_path, "error": str(exc)},
                    )

        return invoked
