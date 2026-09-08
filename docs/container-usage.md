# OCI container usage

The CPU and GPU images run the existing folder-replacement command with fixed roots:
`/input` and `/output`. Do not pass input or output paths after the image name.
Only normal folder-replacement options follow the image name.

Build the smaller CPU image:

```sh
docker build --platform linux/amd64 --target cpu -t visual-doc-pipeline:cpu .
```

Build the NVIDIA GPU image only when GPU processing is needed:

```sh
docker build --platform linux/amd64 --target gpu -t visual-doc-pipeline:gpu .
```

Both builds select their mutually exclusive `cpu` or `gpu` uv profile from the
same committed root lockfile, and use digest-pinned base images and Python
3.13.14. The CPU image uses normal CPU PaddlePaddle and the verified official
CPU PyTorch wheel; it contains no CUDA, cuDNN, or NVIDIA driver components. The
GPU image uses CUDA 12.6.3 with cuDNN runtime and the reviewed
`paddlepaddle-gpu==3.3.1` wheel. It has no NVIDIA driver; a GPU host supplies
that through its container runtime.

Both images are Linux `x86_64` only. Include `--platform linux/amd64` when
running them so Docker selects the image explicitly. On Apple Silicon, Docker
Desktop runs the CPU image through emulation: it is usable but slower and more
memory-intensive than native ARM64. It cannot provide the NVIDIA GPU path. The
selected PaddlePaddle release has no Linux ARM64 wheel.

## CPU run

```sh
docker run --rm --platform linux/amd64 --tty \
  --mount type=bind,src="$PWD/sample-data/",dst=/input,readonly \
  --mount type=bind,src="$PWD/outputs/results/",dst=/output \
  --mount type=volume,src=visual-doc-pipeline-cache,dst=/runtime-cache \
  --mount type=bind,src="/absolute/path/to/service-account.json",dst=/run/secrets/google-application-credentials.json,readonly \
  visual-doc-pipeline:cpu \
  --source-language ja --target-language en
```

## NVIDIA GPU run

On a Linux x86_64 host with a compatible NVIDIA driver and configured NVIDIA
Container Toolkit, request the GPU from Docker:

```sh
docker run --rm --platform linux/amd64 --tty --gpus all \
  --mount type=bind,src="$PWD/sample-data/",dst=/input,readonly \
  --mount type=bind,src="$PWD/outputs/results/",dst=/output \
  --mount type=volume,src=visual-doc-pipeline-cache,dst=/runtime-cache \
  --mount type=bind,src="/absolute/path/to/service-account.json",dst=/run/secrets/google-application-credentials.json,readonly \
  visual-doc-pipeline:gpu \
  --source-language ja --target-language en
```

PaddleOCR automatically uses GPU 0 when Docker exposes a compatible device;
there is no pipeline GPU option. This image requires a compatible exposed GPU;
use the CPU image instead when one is not available.

The default text-replacement provider is Google Cloud Translation. The examples
mount its service-account JSON at the fixed secret target. The provider derives
the project from that file and uses `europe-west1`, so no Docker `--env` option
is required for normal use. The credential's project must have billing and the
Cloud Translation API enabled, and its service account must have the Cloud
Translation API User role.

The first run initializes supported PaddleOCR language models and optional Noto
assets before it reads any input. Mount a durable cache to avoid doing that
again:

```sh
--mount type=volume,src=visual-doc-pipeline-cache,dst=/runtime-cache
```

`--tty` gives the existing Rich progress display a pseudo-terminal, so it can
render its live, bounded rows. `--interactive` (`-i`) is not required. For CI
or redirected logs, omit `--tty`; processing remains supported, with non-live
terminal output instead of an updating display.

Check a host and published image without processing a document:

```sh
scripts/validate-container-gpu.sh registry.example/visual-doc-pipeline@sha256:IMAGE_DIGEST
```

It exits non-zero when Docker cannot request a GPU, Paddle is not CUDA-enabled,
or no CUDA device is visible. NVIDIA documents how to configure Docker with
the Container Toolkit at <https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html>.

## Optional mounts

Use each mount only when needed; all are separate from the normal command
options.

```sh
--mount type=bind,src="$PWD/plugins",dst=/plugins,readonly \
--mount type=bind,src="$PWD/fonts",dst=/fonts,readonly
```

`/plugins/ocr/<provider-name>/` and
`/plugins/text_replacement/<provider-name>/` contain trusted Python provider
packages. They must use dependencies already included in the image. They are
not sandboxed and cannot replace built-in provider names. To add dependencies,
build a derived image; install only pinned, hash-verified wheels at build time
and copy the provider code into the derived image. Do not install packages when
the container starts.

For example, a derived image can bring a pre-reviewed wheelhouse and its
explicit hash-pinned requirement file at build time:

```Dockerfile
FROM registry.example/visual-doc-pipeline@sha256:BASE_IMAGE_DIGEST
USER root
COPY plugin-requirements.txt /tmp/plugin-requirements.txt
COPY wheelhouse/ /tmp/wheelhouse/
RUN /app/.venv/bin/python -m pip install --no-index --only-binary=:all: \
    --require-hashes --no-deps -r /tmp/plugin-requirements.txt
COPY plugins/ /plugins/
USER pipeline
```

The derived-image author is responsible for obtaining those wheels through the
same review and provenance process as project dependencies, and for pinning the
base image digest. This does not alter the base image's built-in providers.

`/fonts` is optional and read-only. In source-font layout mode it provides
operator-supplied faces for source measurement only. The pipeline does not copy
or embed them; operators remain responsible for their licensing and suitability.

For Google Cloud Translation, the fixed credential mount sets
`GOOGLE_APPLICATION_CREDENTIALS` only if the caller did not set it explicitly.
`GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_TRANSLATION_LOCATION` are optional
overrides; for example, an operator can select another supported European
location with `--env GOOGLE_CLOUD_TRANSLATION_LOCATION=europe-west3`.
Credentials are never copied into image layers, output, or the runtime cache.

Mount `/input`, `/plugins`, and `/fonts` read-only. Mount `/output` and
`/runtime-cache` as the only writable storage. The image runs as UID 10001; if
your bind-mounted output is not writable by that UID, use a writable named
volume or arrange compatible ownership before launching it.
