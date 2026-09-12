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
credentials first with the [Google Cloud Translation setup guide](google-cloud-translation-setup.md).
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

## Checks

Validate the dependency policy:

```sh
./run.sh scripts/check-dependency-policy.py
```

Run the automated test suite:

```sh
scripts/run-tests.sh
```

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

Prepare OCR inputs from `sample-data/`:

```sh
./run.sh scripts/prepare_ocr_evaluation_inputs.py
```

Generate OCR and text-replacement viewers:

```sh
./run.sh scripts/ocr_evaluations.py
```

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
