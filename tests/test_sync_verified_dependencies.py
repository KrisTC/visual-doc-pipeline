"""Tests for verified dependency synchronization platform selection."""

from __future__ import annotations

from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import sync_verified_dependencies


class SyncVerifiedDependenciesTests(unittest.TestCase):
    # Verifies TR-2026-09-07-01 and SR-2026-09-08-01.
    def test_accepts_a_manylinux_x86_64_cpu_wheel_on_linux(self) -> None:
        self.assertTrue(
            sync_verified_dependencies._platform_matches("manylinux_2_28_x86_64", "linux_x86_64")
        )
        self.assertFalse(
            sync_verified_dependencies._platform_matches("manylinux_2_28_aarch64", "linux_x86_64")
        )

    # Verifies TR-2026-09-07-01 and SR-2026-08-21-02.
    def test_selects_only_non_default_artifacts_reachable_from_the_profile(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            lockfile = root / "uv.lock"
            lockfile.write_text(
                """
[[package]]
name = "paddlepaddle-gpu"
version = "3.3.1"
source = { registry = "https://example.invalid/paddle/" }

[[package]]
name = "torch"
version = "2.13.0+cpu"
source = { registry = "https://example.invalid/torch/" }
""",
                encoding="utf-8",
            )
            exported = subprocess.CompletedProcess[
                str
            ]([], 0, stdout="torch==2.13.0+cpu\n", stderr="")
            with patch("scripts.sync_verified_dependencies.subprocess.run", return_value=exported):
                selected = sync_verified_dependencies._selected_non_default_packages(
                    lockfile,
                    extra="cpu",
                    include_development_dependencies=False,
                    project_root=root,
                )

        self.assertEqual((("torch", "2.13.0+cpu"),), selected)

    # Verifies TR-2026-09-07-01 and SR-2026-08-21-02.
    def test_selects_cuda_artifacts_only_for_a_linux_gpu_profile(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            lockfile = root / "uv.lock"
            lockfile.write_text(
                """
[[package]]
name = "paddlepaddle-gpu"
version = "3.3.1"
source = { registry = "https://example.invalid/paddle/" }

[[package]]
name = "torch"
version = "2.13.0+cpu"
source = { registry = "https://example.invalid/torch/" }
""",
                encoding="utf-8",
            )
            exported = subprocess.CompletedProcess[
                str
            ](
                [],
                0,
                stdout=(
                    "paddlepaddle-gpu==3.3.1 ; sys_platform == 'linux' and platform_machine == 'x86_64'\n"
                    "torch==2.13.0+cpu ; sys_platform == 'linux'\n"
                ),
                stderr="",
            )
            with (
                patch("scripts.sync_verified_dependencies.subprocess.run", return_value=exported),
                patch(
                    "scripts.sync_verified_dependencies._marker_environment",
                    return_value={"sys_platform": "linux", "platform_machine": "x86_64"},
                ),
            ):
                selected = sync_verified_dependencies._selected_non_default_packages(
                    lockfile,
                    extra="gpu",
                    include_development_dependencies=False,
                    project_root=root,
                )

        self.assertEqual(
            (("paddlepaddle-gpu", "3.3.1"), ("torch", "2.13.0+cpu")),
            selected,
        )
