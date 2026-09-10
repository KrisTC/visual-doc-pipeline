# Docker build targets: cpu (the default) and gpu. Both are Linux amd64 only.
# The CPU target has no CUDA components. The GPU target uses CUDA 12.6 and cuDNN 9
# supplied by PaddlePaddle's exact, locked wheel dependencies.  Do not replace the
# GPU base with an nvidia/cuda runtime: that image duplicates those same libraries.
FROM python:3.13.14-slim-bookworm@sha256:67a1e1f215ccda113cfc024e8639049257e88f273898f595b61476d128d387e8 AS build-base

RUN python -m pip install --no-cache-dir uv==0.11.23

WORKDIR /app
COPY approved-dependency-artifact-hashes.toml ./
COPY scripts/check-dependency-policy.py scripts/sync_verified_dependencies.py ./scripts/

# ----------------------------------------
FROM build-base AS build-cpu
COPY pyproject.toml uv.lock ./
# `package = false` means source code is not needed to create this locked venv.
# Keeping it out of this stage lets source-only changes reuse the expensive wheel layer.
# The cpu extra excludes Paddle GPU and CUDA artifacts. PyTorch's CPU wheel is verified under SR-2026-09-08-01.
RUN --mount=type=cache,target=/root/.cache/uv \
    python scripts/sync_verified_dependencies.py --no-dev --extra cpu \
    && rm -f .venv/bin/pip .venv/bin/pip3 .venv/bin/pip3.13

# ----------------------------------------
# Reuse the locked CPU environment when both variants are built locally.  The
# exact GPU sync below removes CPU-only packages and installs the verified GPU
# profile, so only dependencies shared by both profiles are retained.
FROM build-cpu AS build-gpu
# The CUDA Paddle wheel and its CUDA 12.6/cuDNN 9 runtime wheels are verified
# against SR-2026-08-21-01's reviewed digest.
RUN --mount=type=cache,target=/root/.cache/uv \
    python scripts/sync_verified_dependencies.py --no-dev --extra gpu \
    && rm -f .venv/bin/pip .venv/bin/pip3 .venv/bin/pip3.13

# ----------------------------------------
# Keep large, immutable portable fonts in their own source-only stage. Both final
# variants can reuse this layer, and application-source edits cannot invalidate it.
FROM scratch AS runtime-fonts
# Docker COPY treats brackets in source paths as glob syntax; `[[]` matches the literal `[` character.
COPY tests/assets/fonts/NotoSansJP[[]wght].ttf tests/assets/fonts/NotoSerifJP[[]wght].ttf tests/assets/fonts/NotoSansMono[[]wdth,wght].ttf tests/assets/fonts/NotoSansJP-Regular.ttf tests/assets/fonts/NotoSansJP-Bold.ttf tests/assets/fonts/NotoSerifJP-Regular.ttf tests/assets/fonts/NotoSerifJP-Bold.ttf tests/assets/fonts/NotoSansMono-Regular.ttf tests/assets/fonts/NotoSansMono-Bold.ttf /fonts/

# ----------------------------------------
FROM python:3.13.14-slim-bookworm@sha256:67a1e1f215ccda113cfc024e8639049257e88f273898f595b61476d128d387e8 AS runtime-cpu

LABEL org.opencontainers.image.title="visual-doc-pipeline" \
      org.opencontainers.image.variant="cpu"

# Install only runtime native libraries: Fontconfig discovers portable Noto fonts,
# Skia needs EGL/OpenGL, and Paddle's CPU runtime uses libgomp. Remove APT indexes
# in this same layer, then create the fixed container mounts and writable paths.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends fontconfig libegl1 libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin pipeline \
    && mkdir -p /input /output /plugins /fonts /run/secrets /runtime-cache/home /runtime-cache/cache \
    && chown -R pipeline:pipeline /output /runtime-cache

WORKDIR /app

# Copy the locked environment before application source: dependency changes are
# intentionally expensive, whereas a source-only change rebuilds only the small layers below.
COPY --from=build-cpu /app/.venv /app/.venv
COPY --from=runtime-fonts /fonts/ ./tests/assets/fonts/
COPY --chown=root:root pipeline ./pipeline
COPY --chown=root:root scripts ./scripts

ENV HOME=/runtime-cache/home \
    XDG_CACHE_HOME=/runtime-cache/cache \
    VISUAL_DOC_PIPELINE_FONT_CACHE=/runtime-cache/cache/visual-doc-pipeline/fonts \
    PATH=/app/.venv/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin

USER pipeline
ENTRYPOINT ["/app/.venv/bin/python", "/app/scripts/container_entrypoint.py"]
CMD []

# ----------------------------------------
# Ubuntu 24.04 is sufficient: PaddlePaddle's locked GPU wheel installs the exact
# CUDA 12.6/cuDNN 9 user-space libraries it declares. The NVIDIA container runtime
# supplies only the host driver libraries when `--gpus` exposes a device.
FROM ubuntu:24.04@sha256:224a1869083a311ef3f13648a154ba79832fbef6364d31493642ca03082da254 AS runtime-gpu

LABEL org.opencontainers.image.title="visual-doc-pipeline" \
      org.opencontainers.image.variant="gpu"

# Install only runtime native libraries: Fontconfig discovers portable Noto fonts
# and Skia needs EGL/OpenGL. Remove APT indexes in this same layer, then create
# the fixed container mounts and writable paths.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends fontconfig libegl1 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin pipeline \
    && mkdir -p /input /output /plugins /fonts /run/secrets /runtime-cache/home /runtime-cache/cache \
    && chown -R pipeline:pipeline /output /runtime-cache

WORKDIR /app
# CPython 3.13.14 is copied from the digest-pinned builder so it matches pyproject.toml.
# The venv entrypoint is a symlink to this binary; copying `python` and `python3`
# as well would dereference their builder symlinks and create redundant copies.
COPY --from=build-gpu /usr/local/bin/python3.13 /usr/local/bin/python3.13
COPY --from=build-gpu /usr/local/lib/libpython3.13.so.1.0 /usr/local/lib/
COPY --from=build-gpu /usr/local/lib/python3.13 /usr/local/lib/python3.13
COPY --from=build-gpu /app/.venv /app/.venv
COPY --from=runtime-fonts /fonts/ ./tests/assets/fonts/
COPY --chown=root:root pipeline ./pipeline
COPY --chown=root:root scripts ./scripts

ENV HOME=/runtime-cache/home \
    XDG_CACHE_HOME=/runtime-cache/cache \
    VISUAL_DOC_PIPELINE_FONT_CACHE=/runtime-cache/cache/visual-doc-pipeline/fonts \
    PATH=/app/.venv/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
    LD_LIBRARY_PATH=/usr/local/nvidia/lib:/usr/local/nvidia/lib64

USER pipeline
ENTRYPOINT ["/app/.venv/bin/python", "/app/scripts/container_entrypoint.py"]
CMD []

# ----------------------------------------
FROM runtime-gpu AS gpu

# ----------------------------------------
# Keep the smaller CPU image as Docker's default target.
FROM runtime-cpu AS cpu
