"""Behavioural tests for the Argos Translate text-replacement provider."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast
import unittest
from unittest.mock import patch

from pipeline.text_replacement.errors import TextReplacementProviderError
from pipeline.text_replacement.models import TextReplacementRequest, TextReplacementResult
from pipeline.text_replacement_plugins.argos_translate import (
    ArgosTranslateProvider,
    _ArgosModules,
    _ArgosTranslationPackage,
)


@dataclass(frozen=True, slots=True)
class _AvailablePackage:
    from_code: str
    to_code: str
    type: str = "translate"

    def download(self) -> Path:
        return Path(f"{self.from_code}-{self.to_code}.argosmodel")


class _FakePackageModule:
    def __init__(self, packages: list[_AvailablePackage]) -> None:
        self.packages = packages
        self.installed: list[_AvailablePackage] = []
        self.index_updates = 0

    def update_package_index(self) -> None:
        self.index_updates += 1

    def get_available_packages(self) -> list[_ArgosTranslationPackage]:
        return [cast(_ArgosTranslationPackage, package) for package in self.packages]

    def get_installed_packages(self) -> list[_ArgosTranslationPackage]:
        return [cast(_ArgosTranslationPackage, package) for package in self.installed]

    def install_from_path(self, path: Path) -> None:
        package = next(
            package
            for package in self.packages
            if path == Path(f"{package.from_code}-{package.to_code}.argosmodel")
        )
        self.installed.append(package)


class _FakeTranslateModule:
    def __init__(self, package_module: _FakePackageModule, result: str) -> None:
        self.package_module = package_module
        self.result = result
        self.calls: list[tuple[str, str, str]] = []

    def translate(self, text: str, from_code: str, to_code: str) -> str:
        self.calls.append((text, from_code, to_code))
        if not _has_route(self.package_module.installed, from_code, to_code):
            raise LookupError("No installed translation route")
        return self.result


@dataclass(frozen=True, slots=True)
class _FakeSettingsModule:
    remote_package_index: str = (
        "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json"
    )


class ArgosTranslateProviderTests(unittest.TestCase):
    # Verifies FR-2026-08-04-12.
    def test_downloads_a_direct_package_and_translates_primary_language_subtags(self) -> None:
        package_module = _FakePackageModule([_AvailablePackage("en", "es")])
        translate_module = _FakeTranslateModule(package_module, "Hola")

        result = self._replace_with_modules(
            TextReplacementRequest("Hello", False, "en-GB", "es-MX"),
            package_module,
            translate_module,
        )

        self.assertEqual("Hola", result.text)
        self.assertEqual(0.0, result.confidence)
        self.assertEqual({}, result.extra)
        self.assertEqual(1, package_module.index_updates)
        self.assertEqual([_AvailablePackage("en", "es")], package_module.installed)
        self.assertEqual(("Hello", "en", "es"), translate_module.calls[-1])

    # Verifies FR-2026-08-04-12.
    def test_downloads_a_pivot_route_when_no_direct_package_is_available(self) -> None:
        package_module = _FakePackageModule(
            [_AvailablePackage("en", "fr"), _AvailablePackage("fr", "ja")]
        )
        translate_module = _FakeTranslateModule(package_module, "こんにちは")

        result = self._replace_with_modules(
            TextReplacementRequest("Hello", False, "en", "ja"), package_module, translate_module
        )

        self.assertEqual("こんにちは", result.text)
        self.assertEqual(
            [_AvailablePackage("en", "fr"), _AvailablePackage("fr", "ja")],
            package_module.installed,
        )

    # Verifies FR-2026-08-04-12.
    def test_translates_only_a_filename_stem_and_retains_its_suffix(self) -> None:
        package_module = _FakePackageModule([_AvailablePackage("ja", "en")])
        translate_module = _FakeTranslateModule(package_module, "quarterly report")

        result = self._replace_with_modules(
            TextReplacementRequest("四半期報告.pptx", True, "ja", "en"),
            package_module,
            translate_module,
        )

        self.assertEqual("quarterly report.pptx", result.text)
        self.assertEqual(("四半期報告", "ja", "en"), translate_module.calls[-1])

    # Verifies FR-2026-08-04-12.
    def test_rejects_an_unsafe_translated_filename_stem(self) -> None:
        package_module = _FakePackageModule([_AvailablePackage("ja", "en")])
        translate_module = _FakeTranslateModule(package_module, "unsafe/name")

        with self.assertRaises(TextReplacementProviderError):
            self._replace_with_modules(
                TextReplacementRequest("四半期報告.pptx", True, "ja", "en"),
                package_module,
                translate_module,
            )

    # Verifies FR-2026-08-04-12.
    def test_reports_an_unavailable_route_as_a_provider_error(self) -> None:
        package_module = _FakePackageModule([])
        translate_module = _FakeTranslateModule(package_module, "unused")

        with self.assertRaisesRegex(TextReplacementProviderError, "no downloadable route"):
            self._replace_with_modules(
                TextReplacementRequest("Hello", False, "en", "ja"), package_module, translate_module
            )

    # Verifies FR-2026-08-04-12.
    def test_rejects_a_non_official_package_index_before_downloading(self) -> None:
        package_module = _FakePackageModule([_AvailablePackage("en", "ja")])
        translate_module = _FakeTranslateModule(package_module, "こんにちは")

        with self.assertRaisesRegex(TextReplacementProviderError, "non-official package index"):
            self._replace_with_modules(
                TextReplacementRequest("Hello", False, "en", "ja"),
                package_module,
                translate_module,
                _FakeSettingsModule("https://example.invalid/index.json"),
            )
        self.assertEqual([], package_module.installed)

    def _replace_with_modules(
        self,
        request: TextReplacementRequest,
        package_module: _FakePackageModule,
        translate_module: _FakeTranslateModule,
        settings_module: _FakeSettingsModule | None = None,
    ) -> TextReplacementResult:
        modules = _ArgosModules(
            package_module, translate_module, settings_module or _FakeSettingsModule()
        )
        with patch(
            "pipeline.text_replacement_plugins.argos_translate._load_argos_modules",
            return_value=modules,
        ):
            return ArgosTranslateProvider().replace(request)


def _has_route(packages: list[_AvailablePackage], source: str, target: str) -> bool:
    """Return whether the installed fake package graph connects two language codes."""
    reachable = {source}
    while True:
        expanded = reachable | {
            package.to_code for package in packages if package.from_code in reachable
        }
        if target in expanded:
            return True
        if expanded == reachable:
            return False
        reachable = expanded
