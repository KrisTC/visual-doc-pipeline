"""Discovery and lookup of codebase text-replacement provider plugins."""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from pkgutil import iter_modules
from types import ModuleType
from typing import cast

from pipeline.text_replacement.errors import (
    DuplicateTextReplacementProviderError,
    TextReplacementProviderNotFoundError,
)
from pipeline.text_replacement.provider import TextReplacementProvider


ProviderConstructor = Callable[[], TextReplacementProvider]
PluginRegistration = Callable[["TextReplacementProviderFactory"], None]
PLUGIN_PACKAGE = "pipeline.text_replacement_plugins"


class TextReplacementProviderFactory:
    """Creates providers registered by modules in the default plugin package."""

    def __init__(self) -> None:
        self._constructors: dict[str, ProviderConstructor] = {}

    @classmethod
    def discover_default_plugins(cls) -> "TextReplacementProviderFactory":
        """Discover and register all modules in ``pipeline.text_replacement_plugins``."""
        factory = cls()
        plugin_package = import_module(PLUGIN_PACKAGE)
        package_paths = _package_paths(plugin_package)
        for module_info in iter_modules(package_paths, f"{PLUGIN_PACKAGE}."):
            plugin_module = import_module(module_info.name)
            _register_plugin(plugin_module, factory)
        return factory

    def register(self, name: str, constructor: ProviderConstructor) -> None:
        """Register a provider constructor under a unique, non-empty name."""
        if not name.strip():
            message = "A text-replacement provider name must not be empty."
            raise ValueError(message)
        if name in self._constructors:
            message = f"A text-replacement provider named {name!r} is already registered."
            raise DuplicateTextReplacementProviderError(message)
        self._constructors[name] = constructor

    def create(self, name: str) -> TextReplacementProvider:
        """Create the provider registered under ``name``."""
        try:
            constructor = self._constructors[name]
        except KeyError as error:
            message = f"No text-replacement provider is registered under {name!r}."
            raise TextReplacementProviderNotFoundError(message) from error
        return constructor()

    @property
    def provider_names(self) -> tuple[str, ...]:
        """Return registered names in deterministic order."""
        return tuple(sorted(self._constructors))


def _package_paths(plugin_package: ModuleType) -> list[str]:
    package_paths = getattr(plugin_package, "__path__", None)
    if package_paths is None:
        message = f"{PLUGIN_PACKAGE} is not a package."
        raise RuntimeError(message)
    return list(package_paths)


def _register_plugin(
    plugin_module: ModuleType, factory: TextReplacementProviderFactory
) -> None:
    registration = getattr(plugin_module, "register_providers", None)
    if not callable(registration):
        message = (
            f"Text-replacement plugin {plugin_module.__name__!r} "
            "has no register_providers function."
        )
        raise RuntimeError(message)
    # Plugin modules are discovered dynamically; their registration function cannot be typed statically.
    register = cast(PluginRegistration, registration)
    register(factory)
