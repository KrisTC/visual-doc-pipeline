# Docker build targets: cpu (the default) and gpu. Both are Linux amd64 only.
# The CPU target has no CUDA components. The GPU target uses CUDA 12.6 and cuDNN 9.
FROM python:3.13.14-slim-bookworm@sha256:67a1e1f215ccda113cfc024e8639049257e88f273898f595b61476d128d387e8 AS build-base

RUN python -m pip install --no-cache-dir uv==0.11.23

WORKDIR /app
COPY approved-dependency-artifact-hashes.toml ./
COPY scripts/check-dependency-policy.py scripts/sync_verified_dependencies.py ./scripts/

FROM build-base AS build-cpu
COPY pyproject.toml uv.lock ./
COPY pipeline ./pipeline
# The cpu extra excludes Paddle GPU and CUDA artifacts. PyTorch's CPU wheel is verified under SR-2026-09-08-01.
RUN --mount=type=cache,target=/root/.cache/uv \
    python scripts/sync_verified_dependencies.py --no-dev --extra cpu \
    && rm -f .venv/bin/pip .venv/bin/pip3 .venv/bin/pip3.13

FROM build-base AS build-gpu
COPY pyproject.toml uv.lock ./
COPY pipeline ./pipeline
# The CUDA Paddle wheel is verified against SR-2026-08-21-01's reviewed digest.
RUN --mount=type=cache,target=/root/.cache/uv \
    python scripts/sync_verified_dependencies.py --no-dev --extra gpu \
    && rm -f .venv/bin/pip .venv/bin/pip3 .venv/bin/pip3.13

FROM python:3.13.14-slim-bookworm@sha256:67a1e1f215ccda113cfc024e8639049257e88f273898f595b61476d128d387e8 AS runtime-cpu

LABEL org.opencontainers.image.title="visual-doc-pipeline" \
      org.opencontainers.image.variant="cpu"

RUN apt-get update \
    && apt-get install --yes --no-install-recommends fontconfig libegl1 libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin pipeline \
    && mkdir -p /input /output /plugins /fonts /run/secrets /runtime-cache/home /runtime-cache/cache \
    && chown -R pipeline:pipeline /output /runtime-cache

WORKDIR /app
COPY --from=build-cpu /app/.venv /app/.venv
COPY --chown=root:root pipeline ./pipeline
COPY --chown=root:root scripts ./scripts
# Docker COPY treats brackets in source paths as glob syntax; `[[]` matches the literal `[` character.
COPY --chown=root:root tests/assets/fonts/NotoSansJP[[]wght].ttf tests/assets/fonts/NotoSerifJP[[]wght].ttf tests/assets/fonts/NotoSansMono[[]wdth,wght].ttf tests/assets/fonts/NotoSansJP-Regular.ttf tests/assets/fonts/NotoSansJP-Bold.ttf tests/assets/fonts/NotoSerifJP-Regular.ttf tests/assets/fonts/NotoSerifJP-Bold.ttf tests/assets/fonts/NotoSansMono-Regular.ttf tests/assets/fonts/NotoSansMono-Bold.ttf ./tests/assets/fonts/

ENV HOME=/runtime-cache/home \
    XDG_CACHE_HOME=/runtime-cache/cache \
    VISUAL_DOC_PIPELINE_FONT_CACHE=/runtime-cache/cache/visual-doc-pipeline/fonts \
    PATH=/app/.venv/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin

USER pipeline
ENTRYPOINT ["/app/.venv/bin/python", "/app/scripts/container_entrypoint.py"]
CMD []

FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04@sha256:23debbe74125dc84df96df79cff42079b3b15265c27140714fd27b5aa718faa4 AS runtime-gpu

LABEL org.opencontainers.image.title="visual-doc-pipeline" \
      org.opencontainers.image.variant="gpu"

RUN apt-get update \
    && apt-get install --yes --no-install-recommends fontconfig libegl1 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && ldconfig \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin pipeline \
    && mkdir -p /input /output /plugins /fonts /run/secrets /runtime-cache/home /runtime-cache/cache \
    && chown -R pipeline:pipeline /output /runtime-cache

WORKDIR /app
# CPython 3.13.14 is copied from the digest-pinned builder so it matches pyproject.toml.
COPY --from=build-gpu /usr/local/bin/python /usr/local/bin/python
COPY --from=build-gpu /usr/local/bin/python3 /usr/local/bin/python3
COPY --from=build-gpu /usr/local/bin/python3.13 /usr/local/bin/python3.13
COPY --from=build-gpu /usr/local/lib/libpython3.13.so.1.0 /usr/local/lib/
COPY --from=build-gpu /usr/local/lib/python3.13 /usr/local/lib/python3.13
COPY --from=build-gpu /app/.venv /app/.venv
COPY --chown=root:root pipeline ./pipeline
COPY --chown=root:root scripts ./scripts
COPY --chown=root:root tests/assets/fonts/NotoSansJP[[]wght].ttf tests/assets/fonts/NotoSerifJP[[]wght].ttf tests/assets/fonts/NotoSansMono[[]wdth,wght].ttf tests/assets/fonts/NotoSansJP-Regular.ttf tests/assets/fonts/NotoSansJP-Bold.ttf tests/assets/fonts/NotoSerifJP-Regular.ttf tests/assets/fonts/NotoSerifJP-Bold.ttf tests/assets/fonts/NotoSansMono-Regular.ttf tests/assets/fonts/NotoSansMono-Bold.ttf ./tests/assets/fonts/

ENV HOME=/runtime-cache/home \
    XDG_CACHE_HOME=/runtime-cache/cache \
    VISUAL_DOC_PIPELINE_FONT_CACHE=/runtime-cache/cache/visual-doc-pipeline/fonts \
    PATH=/app/.venv/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
    LD_LIBRARY_PATH=/usr/local/cuda/lib64

USER pipeline
ENTRYPOINT ["/app/.venv/bin/python", "/app/scripts/container_entrypoint.py"]
CMD []

FROM runtime-gpu AS gpu

# Keep the smaller CPU image as Docker's default target.
FROM runtime-cpu AS cpu
