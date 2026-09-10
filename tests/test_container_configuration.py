"""Static checks for the reproducible OCI build definition."""

from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


class ContainerConfigurationTests(unittest.TestCase):
    # Verifies TR-2026-09-07-01 and SR-2026-09-07-01.
    def test_dockerfile_defines_pinned_cpu_and_gpu_images_with_fixed_mounts(self) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn("python:3.13.14-slim-bookworm@sha256:", dockerfile)
        self.assertIn("ubuntu:24.04@sha256:", dockerfile)
        self.assertNotIn("nvidia/cuda:", dockerfile)
        self.assertIn("COPY pyproject.toml uv.lock ./", dockerfile)
        self.assertIn("sync_verified_dependencies.py --no-dev --extra cpu", dockerfile)
        self.assertIn("sync_verified_dependencies.py --no-dev --extra gpu", dockerfile)
        # Verifies TR-2026-09-07-01: GPU synchronisation transforms the locked
        # CPU environment instead of reinstalling their shared dependencies.
        self.assertIn("FROM build-cpu AS build-gpu", dockerfile)
        self.assertIn("FROM runtime-cpu AS cpu", dockerfile)
        self.assertIn("FROM runtime-gpu AS gpu", dockerfile)
        self.assertIn("COPY --from=build-gpu /usr/local/bin/python3.13 /usr/local/bin/python3.13", dockerfile)
        self.assertNotIn("COPY --from=build-gpu /usr/local/bin/python /usr/local/bin/python", dockerfile)
        self.assertNotIn("COPY --from=build-gpu /usr/local/bin/python3 /usr/local/bin/python3", dockerfile)
        self.assertIn("USER pipeline", dockerfile)
        self.assertIn("fontconfig libegl1 libgl1 libglib2.0-0 libgomp1", dockerfile)
        self.assertIn("fontconfig libegl1 libgl1 libglib2.0-0", dockerfile)
        self.assertIn("ENTRYPOINT [\"/app/.venv/bin/python\", \"/app/scripts/container_entrypoint.py\"]", dockerfile)
        self.assertIn("/input /output /plugins /fonts /run/secrets /runtime-cache", dockerfile)
        for font_asset in (
            "NotoSansJP[[]wght].ttf",
            "NotoSerifJP[[]wght].ttf",
            "NotoSansMono[[]wdth,wght].ttf",
            "NotoSansJP-Regular.ttf",
            "NotoSansJP-Bold.ttf",
            "NotoSerifJP-Regular.ttf",
            "NotoSerifJP-Bold.ttf",
            "NotoSansMono-Regular.ttf",
            "NotoSansMono-Bold.ttf",
        ):
            self.assertIn(font_asset, dockerfile)
        self.assertIn("[project.optional-dependencies]", pyproject)
        self.assertIn("cpu = [", pyproject)
        self.assertIn("gpu = [", pyproject)
        self.assertIn('[{ extra = "cpu" }, { extra = "gpu" }]', pyproject)
        self.assertNotIn("EXPOSE", dockerfile)

    # Verifies FR-2026-09-07-02 and SR-2026-09-07-01.
    def test_container_entrypoint_does_not_install_or_resolve_plugin_dependencies(self) -> None:
        entrypoint = (ROOT / "scripts" / "container_entrypoint.py").read_text(encoding="utf-8")

        self.assertNotIn("subprocess", entrypoint)
        self.assertNotIn("pip install", entrypoint)
        self.assertNotIn("uv sync", entrypoint)

    # Verifies FR-2026-09-07-03.
    def test_gpu_validation_requests_a_device_when_starting_the_image(self) -> None:
        command = (ROOT / "scripts" / "validate-container-gpu.sh").read_text(encoding="utf-8")

        self.assertIn("docker run --rm --gpus all", command)
        self.assertIn("validate_container_gpu.py", command)

    # Verifies FR-2026-09-07-01.
    def test_container_examples_request_a_tty_for_live_rich_progress(self) -> None:
        usage = (ROOT / "docs" / "container-usage.md").read_text(encoding="utf-8")

        self.assertIn("--target cpu -t visual-doc-pipeline:cpu", usage)
        self.assertIn("--target gpu -t visual-doc-pipeline:gpu", usage)
        self.assertIn("docker run --rm --platform linux/amd64 --tty \\", usage)
        self.assertIn("docker run --rm --platform linux/amd64 --tty --gpus all \\", usage)
        self.assertEqual(2, usage.count("dst=/run/secrets/google-application-credentials.json,readonly"))
        self.assertIn("derives\nthe project from that file and uses `europe-west1`", usage)
        self.assertIn("`--interactive` (`-i`) is not required", usage)
        self.assertIn("Apple Silicon", usage)
