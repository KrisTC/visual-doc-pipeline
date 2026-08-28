"""Discovery and lookup of codebase OCR-provider plugins."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from importlib import import_module
from inspect import cleandoc
from pkgutil import iter_modules
from types import MappingProxyType, ModuleType
from typing import cast

from pipeline.ocr.errors import OcrProviderNotFoundError
from pipeline.ocr.provider import OcrProvider
from pipeline.provider_cache import CachingOcrProvider, caching_is_enabled


ProviderCreator = Callable[[], OcrProvider]
PLUGIN_PACKAGE = "pipeline.ocr_plugins"


class OcrProviderFactory:
    """Creates OCR providers discovered from the default provider-package directory."""

    def __init__(
        self,
        creators: Mapping[str, ProviderCreator] | None = None,
        descriptions: Mapping[str, str | None] | None = None,
        cache_identities: Mapping[str, Callable[[], str] | None] | None = None,
    ) -> None:
        self._creators = dict(creators or {})
        self._cache_identities = {
            name: cache_identities.get(name) if cache_identities is not None else None
            for name in self._creators
        }
        self._provider_descriptions: Mapping[str, str | None] = MappingProxyType(
            {
                name: descriptions.get(name) if descriptions is not None else None
                for name in self._creators
            }
        )

    @classmethod
    def discover_default_plugins(cls) -> "OcrProviderFactory":
        """Discover provider packages in ``pipeline.ocr_plugins`` without creating them."""
        plugin_package = import_module(PLUGIN_PACKAGE)
        package_paths = _package_paths(plugin_package)
        creators: dict[str, ProviderCreator] = {}
        descriptions: dict[str, str | None] = {}
        cache_identities: dict[str, Callable[[], str] | None] = {}
        for module_info in iter_modules(package_paths, f"{PLUGIN_PACKAGE}."):
            if not module_info.ispkg:
                continue
            plugin_module = import_module(module_info.name)
            provider_name = module_info.name.rpartition(".")[2]
            creators[provider_name] = _provider_creator(plugin_module)
            descriptions[provider_name] = _description(plugin_module.__doc__)
            cache_identities[provider_name] = _cache_identity(plugin_module)
        return cls(creators, descriptions, cache_identities)

    def create(self, name: str) -> OcrProvider:
        """Create the provider stored under its package-derived ``name``."""
        try:
            creator = self._creators[name]
        except KeyError as error:
            message = f"No OCR provider is registered under {name!r}."
            raise OcrProviderNotFoundError(message) from error
        provider = creator()
        cache_identity = self._cache_identities[name]
        if not caching_is_enabled() or cache_identity is None:
            return provider
        try:
            identity = cache_identity()
        except Exception:
            return provider
        if not isinstance(identity, str) or not identity.strip():
            return provider
        return CachingOcrProvider(provider, f"{name}:{identity}")

    @property
    def provider_names(self) -> tuple[str, ...]:
        """Return discovered package-derived names in deterministic order."""
        return tuple(sorted(self._creators))

    @property
    def provider_descriptions(self) -> Mapping[str, str | None]:
        """Return read-only descriptions keyed by package-derived provider name."""
        return self._provider_descriptions


def _package_paths(plugin_package: ModuleType) -> list[str]:
    package_paths = getattr(plugin_package, "__path__", None)
    if package_paths is None:
        message = f"{PLUGIN_PACKAGE} is not a package."
        raise RuntimeError(message)
    return list(package_paths)


def _provider_creator(plugin_module: ModuleType) -> ProviderCreator:
    creator = getattr(plugin_module, "create_provider", None)
    if not callable(creator):
        message = f"OCR plugin package {plugin_module.__name__!r} has no create_provider function."
        raise RuntimeError(message)
    # Plugin packages are discovered dynamically; their creator function cannot be typed statically.
    return cast(ProviderCreator, creator)


def _description(docstring: str | None) -> str | None:
    """Normalize an optional provider-package docstring for factory metadata."""
    if docstring is None:
        return None
    return cleandoc(docstring) or None


def _cache_identity(plugin_module: ModuleType) -> Callable[[], str] | None:
    """Return a plugin's optional output-compatibility cache identity."""
    identity = getattr(plugin_module, "cache_identity", None)
    if identity is None:
        return None
    if not callable(identity):
        message = f"OCR plugin package {plugin_module.__name__!r} has an invalid cache_identity."
        raise RuntimeError(message)
    return cast(Callable[[], str], identity)
