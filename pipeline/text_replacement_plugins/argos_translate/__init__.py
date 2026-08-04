"""Offline Argos Translate text and filename translation provider."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast

from pipeline.text_replacement.errors import TextReplacementProviderError
from pipeline.text_replacement.models import TextReplacementRequest, TextReplacementResult
from pipeline.text_replacement.provider import TextReplacementProvider


LOCAL_EVALUATION_ELIGIBLE = False
_OFFICIAL_PACKAGE_INDEX_URL = "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json"


class _ArgosTranslationPackage(Protocol):
    """The subset of an Argos package used to discover a translation route."""

    from_code: str
    to_code: str
    type: str

    def download(self) -> Path:
        """Download this package to Argos's configured local cache."""


class _ArgosPackageModule(Protocol):
    """The Argos package API boundary used by this provider."""

    def update_package_index(self) -> None:
        """Refresh the locally cached package index."""

    def get_available_packages(self) -> list[_ArgosTranslationPackage]:
        """Return packages published in the configured index."""

    def get_installed_packages(self) -> list[_ArgosTranslationPackage]:
        """Return packages already installed in the configured local store."""

    def install_from_path(self, path: Path) -> None:
        """Install an Argos model archive from the local download cache."""


class _ArgosTranslateModule(Protocol):
    """The Argos translation API boundary used by this provider."""

    def translate(self, text: str, from_code: str, to_code: str) -> str:
        """Translate text through an installed direct or pivot route."""


class _ArgosSettingsModule(Protocol):
    """The configured Argos package-index location."""

    @property
    def remote_package_index(self) -> str:
        """Return the package-index URL configured for this Argos process."""


@dataclass(frozen=True, slots=True)
class _ArgosModules:
    """Dynamically loaded Argos modules, isolated from the typed pipeline API."""

    package: _ArgosPackageModule
    translate: _ArgosTranslateModule
    settings: _ArgosSettingsModule


class ArgosTranslateProvider:
    """Translate text locally, downloading official Argos packages when needed."""

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        """Translate one request, preserving an input filename's suffix unchanged."""
        source_code = _argos_language_code(request.source_language)
        target_code = _argos_language_code(request.target_language)
        if not request.text or source_code == target_code:
            return TextReplacementResult(text=request.text, confidence=0.0)

        filename_suffix = ""
        text = request.text
        if request.is_filename:
            filename = Path(request.text)
            filename_suffix = filename.suffix
            text = filename.stem

        translated = self._translate(text, source_code, target_code)
        if request.is_filename:
            _validate_filename_stem(translated)
            translated = f"{translated}{filename_suffix}"
        return TextReplacementResult(text=translated, confidence=0.0)

    def _translate(self, text: str, source_code: str, target_code: str) -> str:
        """Use an installed route, or install the shortest available package route."""
        modules = _load_argos_modules()
        try:
            return modules.translate.translate(text, source_code, target_code)
        except Exception as initial_error:
            try:
                _ensure_official_package_index(modules.settings)
                modules.package.update_package_index()
                route = _find_package_route(
                    modules.package.get_available_packages(), source_code, target_code
                )
                if route is None:
                    message = (
                        "Argos Translate has no downloadable route from "
                        f"{source_code!r} to {target_code!r}."
                    )
                    raise TextReplacementProviderError(message) from initial_error
                installed_edges = {
                    _package_edge(package) for package in modules.package.get_installed_packages()
                }
                for package in route:
                    if _package_edge(package) not in installed_edges:
                        modules.package.install_from_path(package.download())
                return modules.translate.translate(text, source_code, target_code)
            except TextReplacementProviderError:
                raise
            except Exception as error:
                message = (
                    "Argos Translate could not translate from "
                    f"{source_code!r} to {target_code!r}."
                )
                raise TextReplacementProviderError(message) from error


def create_provider() -> TextReplacementProvider:
    """Create the Argos Translate provider selected by this package's directory name."""
    return ArgosTranslateProvider()


def _load_argos_modules() -> _ArgosModules:
    """Load Argos only when a request needs it, avoiding discovery-time filesystem writes."""
    # Argos does not publish type information; this confines its dynamic module boundary.
    package = cast(_ArgosPackageModule, import_module("argostranslate.package"))
    translate = cast(_ArgosTranslateModule, import_module("argostranslate.translate"))
    settings = cast(_ArgosSettingsModule, import_module("argostranslate.settings"))
    return _ArgosModules(package, translate, settings)


def _ensure_official_package_index(settings: _ArgosSettingsModule) -> None:
    """Reject an Argos configuration that would acquire packages from another index."""
    if settings.remote_package_index != _OFFICIAL_PACKAGE_INDEX_URL:
        message = "Argos Translate is configured with a non-official package index."
        raise TextReplacementProviderError(message)


def _argos_language_code(language_tag: str) -> str:
    """Map a BCP 47 tag to the primary language code accepted by Argos."""
    return language_tag.strip().replace("_", "-").split("-", maxsplit=1)[0].lower()


def _find_package_route(
    packages: list[_ArgosTranslationPackage], source_code: str, target_code: str
) -> list[_ArgosTranslationPackage] | None:
    """Find the fewest Argos translation packages connecting the requested languages."""
    outgoing: dict[str, list[_ArgosTranslationPackage]] = {}
    for package in packages:
        if package.type != "translate":
            continue
        package_source, _ = _package_edge(package)
        outgoing.setdefault(package_source, []).append(package)

    queue: deque[tuple[str, list[_ArgosTranslationPackage]]] = deque([(source_code, [])])
    visited = {source_code}
    while queue:
        current_code, route = queue.popleft()
        for package in outgoing.get(current_code, []):
            _, next_code = _package_edge(package)
            next_route = [*route, package]
            if next_code == target_code:
                return next_route
            if next_code not in visited:
                visited.add(next_code)
                queue.append((next_code, next_route))
    return None


def _package_edge(package: _ArgosTranslationPackage) -> tuple[str, str]:
    """Return a package's normalized directed language edge."""
    return (_argos_language_code(package.from_code), _argos_language_code(package.to_code))


def _validate_filename_stem(stem: str) -> None:
    """Reject translated stems that cannot safely become a destination filename."""
    if not stem or stem in {".", ".."} or "\x00" in stem or "/" in stem or "\\" in stem:
        message = "Argos Translate returned an unsafe translated filename stem."
        raise TextReplacementProviderError(message)
