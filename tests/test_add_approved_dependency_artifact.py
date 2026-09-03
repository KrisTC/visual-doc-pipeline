"""Tests for locally reviewed dependency-artifact allowlist generation."""

from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from scripts import add_approved_dependency_artifact as approval


class ApprovedDependencyArtifactTests(unittest.TestCase):
    # Verifies SR-2026-08-21-02.
    def test_add_artifacts_writes_every_discovered_wheel_sibling(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            allowlist = root / "approved-dependency-artifact-hashes.toml"
            wheel = root / "demo_package-1.2.3-cp313-cp313-win_amd64.whl"
            _write_wheel(wheel, "demo-package", "1.2.3")
            artifact_url = "https://registry.example/simple/demo-package/demo_package-1.2.3-cp313-cp313-win_amd64.whl"
            expected_digest = hashlib.sha256(wheel.read_bytes()).hexdigest()

            with (
                patch.object(approval, "_validate_inputs"),
                patch.object(approval, "_wheel_urls", return_value=(artifact_url,)),
                patch.object(approval, "_download_artifact", wraps=lambda *values: _copy_artifact(wheel, *values)),
                patch.object(approval, "CACHE_DIRECTORY", root / "cache"),
            ):
                artifacts = approval.add_artifacts(
                    "SR-2026-08-21-01",
                    "https://registry.example/simple/",
                    "demo-package",
                    "1.2.3",
                    allowlist,
                )

            self.assertEqual(1, len(artifacts))
            self.assertEqual(expected_digest, artifacts[0].sha256)
            allowlist_text = allowlist.read_text(encoding="utf-8")
            self.assertIn('requirement = "SR-2026-08-21-01"', allowlist_text)
            self.assertIn(f'sha256 = "{expected_digest}"', allowlist_text)

    # Verifies SR-2026-08-21-02.
    def test_add_artifacts_resumes_missing_siblings(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            allowlist = root / "allowlist.toml"
            first_url = "https://registry.example/simple/demo-package/demo_package-1.2.3-cp313-cp313-win_amd64.whl"
            second_url = "https://registry.example/simple/demo-package/demo_package-1.2.3-cp313-cp313-manylinux_x86_64.whl"
            existing = approval.Artifact(
                "SR-2026-08-21-01", "demo-package", "1.2.3", first_url, "0" * 64, 1, "cp313-cp313-win_amd64"
            )
            new_artifact = approval.Artifact(
                "SR-2026-08-21-01", "demo-package", "1.2.3", second_url, "1" * 64, 2, "cp313-cp313-manylinux_x86_64"
            )

            with (
                patch.object(approval, "_validate_inputs"),
                patch.object(approval, "_wheel_urls", return_value=(first_url, second_url)),
                patch.object(approval, "_download_artifact", return_value=new_artifact) as download,
                patch.object(approval, "_load_allowlist", return_value=[existing]),
                patch.object(approval, "CACHE_DIRECTORY", root / "cache"),
            ):
                artifacts = approval.add_artifacts(
                    "SR-2026-08-21-01", "https://registry.example/simple/", "demo-package", "1.2.3", allowlist
                )

            download.assert_called_once()
            self.assertEqual({first_url, second_url}, {artifact.url for artifact in artifacts})

    # Verifies SR-2026-08-21-02.
    def test_add_artifacts_discards_stale_python_version_records(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            allowlist = root / "allowlist.toml"
            old_url = "https://registry.example/simple/demo-package/demo_package-1.2.3-cp312-cp312-win_amd64.whl"
            current_url = "https://registry.example/simple/demo-package/demo_package-1.2.3-cp313-cp313-win_amd64.whl"
            old_artifact = approval.Artifact(
                "SR-2026-08-21-01", "demo-package", "1.2.3", old_url, "0" * 64, 1, "cp312-cp312-win_amd64"
            )
            current_artifact = approval.Artifact(
                "SR-2026-08-21-01", "demo-package", "1.2.3", current_url, "1" * 64, 2, "cp313-cp313-win_amd64"
            )

            with (
                patch.object(approval, "_validate_inputs"),
                patch.object(approval, "_wheel_urls", return_value=(current_url,)),
                patch.object(approval, "_load_allowlist", return_value=[old_artifact, current_artifact]),
                patch.object(approval, "CACHE_DIRECTORY", root / "cache"),
            ):
                artifacts = approval.add_artifacts(
                    "SR-2026-08-21-01", "https://registry.example/simple/", "demo-package", "1.2.3", allowlist
                )

            self.assertEqual((current_artifact,), artifacts)
            self.assertNotIn(old_url, allowlist.read_text(encoding="utf-8"))

    # Verifies SR-2026-08-21-02.
    def test_rejects_direct_wheel_url_as_registry_input(self) -> None:
        with self.assertRaisesRegex(ValueError, "direct wheel URL"):
            approval.add_artifacts(
                "SR-2026-08-21-01",
                "https://registry.example/demo_package-1.2.3-py3-none-any.whl",
                "demo-package",
                "1.2.3",
                Path("unused.toml"),
            )

    # Verifies SR-2026-08-21-02.
    def test_wheel_urls_selects_only_project_supported_python_tags(self) -> None:
        page = """<a href=\"demo_package-1.2.3-cp312-cp312-win_amd64.whl\">old</a>
        <a href=\"demo_package-1.2.3-cp313-cp313-win_amd64.whl\">current</a>"""
        with (
            patch.object(approval, "urlopen", return_value=_Response(page.encode("utf-8"))),
            patch.object(approval, "_supported_cpython_tags", return_value=frozenset({"cp313"})),
        ):
            urls = approval._wheel_urls("https://registry.example/simple/", "demo-package", "1.2.3")  # pyright: ignore[reportPrivateUsage]

        self.assertEqual(
            ("https://registry.example/simple/demo-package/demo_package-1.2.3-cp313-cp313-win_amd64.whl",),
            urls,
        )

    # Verifies SR-2026-08-21-02.
    def test_rejects_existing_records_without_replace(self) -> None:
        artifact = approval.Artifact(
            "SR-2026-08-21-01", "demo-package", "1.2.3", "https://example.test/demo.whl", "0" * 64, 1, "py3-none-any"
        )
        with TemporaryDirectory() as temporary_directory:
            allowlist = Path(temporary_directory) / "allowlist.toml"
            with (
                patch.object(approval, "_validate_inputs"),
                patch.object(approval, "_wheel_urls", return_value=(artifact.url,)),
                patch.object(approval, "_load_allowlist", return_value=[artifact]),
                self.assertRaisesRegex(ValueError, "use --replace"),
            ):
                approval.add_artifacts(
                    artifact.requirement,
                    "https://registry.example/simple/",
                    artifact.distribution,
                    artifact.version,
                    allowlist,
                )


def _write_wheel(path: Path, name: str, version: str) -> None:
    with ZipFile(path, "w") as archive:
        archive.writestr(f"{name.replace('-', '_')}-{version}.dist-info/METADATA", f"Name: {name}\nVersion: {version}\n")


def _copy_artifact(wheel: Path, *values: object) -> approval.Artifact:
    requirement, distribution, version, url, _ = values[:5]
    filename = wheel.name.removesuffix(".whl")
    wheel_tags = "-".join(filename.rsplit("-", maxsplit=3)[-3:])
    return approval.Artifact(
        str(requirement),
        str(distribution),
        str(version),
        str(url),
        hashlib.sha256(wheel.read_bytes()).hexdigest(),
        wheel.stat().st_size,
        wheel_tags,
    )


class _Response:
    def __init__(self, content: bytes) -> None:
        self._content = content

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, exception_type: object, exception: object, traceback: object) -> None:
        del exception_type, exception, traceback

    def read(self) -> bytes:
        return self._content
