# Local development

This page is for contributors and local evaluators. For normal document
processing, use the [container workflow](container-usage.md).

## Environment setup

The project uses Python 3.13.14 and [uv](https://docs.astral.sh/uv/). Create or
update the local environment from the committed lockfile:

```sh
uv run --no-sync python scripts/sync_verified_dependencies.py --extra gpu
```

Run the main command locally with explicit input and output folders:

```sh
./run.sh scripts/folder_replacement.py INPUT_FOLDER OUTPUT_FOLDER \
  --source-language ja --target-language en
```

The default text-replacement provider is Google Cloud Translation. Configure
credentials first with the [Google Cloud setup guide](google-cloud-setup.md).
For local translation, select Argos explicitly:

```sh
./run.sh scripts/folder_replacement.py INPUT_FOLDER OUTPUT_FOLDER \
  --source-language ja --target-language en \
  --text-replacement argos_translate
```

See the current CLI surface with:

```sh
./run.sh scripts/folder_replacement.py --help
```

Inspect aggregate counts and known provider-call timings from an existing
source-adjacent cache (without enabling caching or reading cached results):

```sh
./run.sh scripts/cache_metrics.py INPUT_FILE.plugin-cache.sqlite3
```

The JSON output separates unattributed legacy rows (`provider_name: null`)
from named providers. Unknown input lengths and durations remain unknown.
With `--debug`, folder replacement also writes per-document run activity and,
when an existing cache is available, a separate cache-inventory snapshot.
Keep cache sidecars and diagnostics derived from confidential sources local.

## Checks

Validate the dependency policy:

```sh
./run.sh scripts/check-dependency-policy.py
```

Run the automated test suite. By default it runs in parallel with `pytest` and
`pytest-xdist`, using `max(1, cores - 2)` workers:

```sh
scripts/run-tests.sh            # Windows: .\scripts\run-tests.ps1
```

Options handled by the runner:

| Option | Effect |
|---|---|
| `--serial` | Run in one process with `unittest` discovery, the reference mode for reproducing a failure. CI uses this. |
| `--fast` | Skip tests marked `@slow_test` (`tests/slow_test_support.py`); they are reported as skipped. Use it while iterating; run without it before finishing. |
| `--workers N` | Set the parallel worker count. |

Any other argument is passed to `pytest`, or to `unittest` with `--serial`, for
example `scripts/run-tests.sh -k name_pattern --durations 20` or
`scripts/run-tests.sh --serial -v`. Each tool has its own options; `pytest`
accepts file paths and `-k` expressions, whereas `unittest discover` accepts
`-k` patterns and `--durations`.

Type-check Python:

```sh
./run.sh scripts/typecheck-python.py
```

## Windows NVIDIA GPU OCR

On Windows, the locked environment uses PaddlePaddle's CUDA 12.6 GPU wheel and
selects GPU 0 when the NVIDIA runtime is available. GPU support requires an x64
NVIDIA CUDA 12 runtime, an x64 cuDNN 9 runtime in the child-process `PATH`, and
a compatible NVIDIA driver.

The following archived installers were verified with the current PaddlePaddle
wheel:

- [CUDA Toolkit 12.0 for Windows x86_64](https://developer.nvidia.com/cuda-12-0-0-download-archive?target_os=Windows&target_arch=x86_64&target_version=11&target_type=exe_local)
- [cuDNN 9.24 for Windows x86_64](https://developer.nvidia.com/cudnn-9-24-0-download-archive?target_os=Windows&target_arch=x86_64&target_version=11)

After installing the x64 variants, generate the ignored local runtime
configuration:

```powershell
& .\scripts\configure-paddle-cuda-environment.ps1
```

The helper selects valid installed CUDA and cuDNN paths, writes only its managed
`PATH` entry to `.env.local`, preserves other local configuration including
provider credentials, and verifies that PaddlePaddle can see a CUDA device.

## Evaluation workflows

Evaluation artifacts are local and ignored by Git.

### Windows EMF previews

Debug-enabled fitted-layout processing records `emf_layout_trace` separately
from issue entries in the per-document diagnostic sidecar. The trace can
contain source and replacement text and must be treated as sensitive local
output. Geometry with an unresolved coordinate space or transform is marked
accordingly; the trace describes processing decisions, not viewer rendering.

On Windows, the development folder-replacement runner automatically invokes
`scripts/emf_preview.py` after completing its scenarios. It can also be run
independently on a revision, a scenario directory, or one processed EMF:

```powershell
.\run.ps1 scripts\emf_preview.py PATH
.\run.ps1 scripts\emf_preview.py PATH --dpi 200
```

The default resolution is 400 DPI. For a processed `file.emf` whose original
is identified by its diagnostic sidecar, `file.emf.diff.png` shows the original
and output side by side using GDI+ playback; `file.emf.diff.gdi.png` does the
same using GDI. Without a matched original, `file.emf.preview.png` and
`file.emf.preview.gdi.png` show only the processed file. EMF+ Only files have no
GDI comparison. Existing generated sidecars are overwritten on rerun; an
opposite-kind or unavailable sidecar left from an earlier run is reported as
potentially stale. A Rich progress display shows overall and per-file progress.

The script deliberately rejects graphics it cannot verify as self-contained,
including external-resource records, unsupported comments (`MULTIFORMATS`,
`WINDOWS_METAFILE`), nested WMF or deeply nested metafiles, texture brushes and
unsupported pen options. A rejection is reported rather
than rendering with a weakened external-resource boundary. Previews are local
diagnostic aids, not guaranteed pixel-identical to Office. The safety limits
are 128 MiB per input EMF and 25 million pixels for a two-panel comparison.
Confidential-derived outputs and supporting artifacts must remain under
`outputs/evaluations/`.

Prepare OCR inputs from `sample-data/`:

```sh
./run.sh scripts/prepare_ocr_evaluation_inputs.py
```

Generate OCR and text-replacement viewers:

```sh
./run.sh scripts/ocr_evaluations.py
```

For a manual Cloud Vision OCR evaluation, follow the [Google Cloud setup guide](google-cloud-setup.md), then select it explicitly:

```sh
./run.sh scripts/ocr_evaluations.py --ocr google_cloud_vision
```

This sends the prepared evaluation images, including confidential samples, to Google. Add `--include 'ja/example.pptx'` to process only a matching source document and its embedded images; the path is relative to `sample-data/`.

By default each run processes at most the first 25 images (after `--include` filtering, in sorted order). Use `--max-images N` to change the cap or `--max-images 0` for no limit. Preparation, cleanup, OCR and each text-replacement provider are shown as stages in the live progress display.

The text-replacement viewer always includes the `identity` and `character_mask` providers. Add one more with `--text-replacement PROVIDER`, for example `argos_translate` or `google_cloud_translate`; the added provider is shown first when the viewer opens. `google_cloud_translate` sends the recognised text, including from confidential samples, to Google Cloud Translation (EU endpoint).

Generate colour-estimation pages:

```sh
./run.sh scripts/colour_evaluations.py
```

Generate text-replacement pages:

```sh
./run.sh scripts/text_replacement_evaluations.py
```

The generated results are written beneath `outputs/evaluations/`. Keep
confidential sample material and derived artifacts local; do not add them to
the repository.
