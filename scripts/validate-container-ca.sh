#!/usr/bin/env sh
# Verify the final images' default Python HTTPS trust against both font sources.
set -eu

if [ "$#" -ne 2 ]; then
    printf '%s\n' 'Usage: scripts/validate-container-ca.sh CPU_IMAGE GPU_IMAGE' >&2
    exit 2
fi

for image in "$@"; do
    printf 'Checking CA trust in %s\n' "$image"
    docker run --rm --interactive --platform linux/amd64 \
        --entrypoint /app/.venv/bin/python "$image" - <<'PY'
import os
import ssl
from urllib.request import urlopen

from pipeline.runtime_assets import _MATH_ARCHIVE_URL, _SYMBOLS_ARCHIVE_URL

if os.getuid() == 0:
    raise RuntimeError("CA check must run as the image's non-root user")
context = ssl.create_default_context()
if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
    raise RuntimeError("Certificate and hostname verification must be enabled")
for url in (_SYMBOLS_ARCHIVE_URL, _MATH_ARCHIVE_URL):
    with urlopen(url, timeout=60) as response:
        print(f"HTTPS OK: {url} (status {response.status})", flush=True)
PY
done
