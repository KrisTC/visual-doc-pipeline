# visual-doc-pipeline

Configurable processing pipeline for finding and replacing visible text in documents, images and images embeded in documents.

Basically I thought it would be fun and interesting to solve the middle hard part of document translation, I haven't come across anything that does this well, except possibly the latest version of https://learn.microsoft.com/en-us/azure/ai-services/translator/document-translation/latest/overview?tabs=async 

| Area | Solved? | My target |
|---|---:|---|
| Replacing text in documents | ✅ | Easy — lots of people do this |
| OCR and translation | ✅ | Hard — lots of people solved this |
| Presentation-aware text replacement | 🎯 | Medium — ensure replacements scale nicely, either as rich-text objects or rendered bitmaps |
| Nested bitmaps in rich-text documents | 🎯 | Medium |

Project requirements are the source of truth and live in [requirements/](requirements/).

## Development setup

This project uses Python 3.13.14 and [uv](https://docs.astral.sh/uv/). Create or update the local environment only from the committed lockfile:

```sh
uv run --no-sync python scripts/sync_verified_dependencies.py
```

Check the dependency source and cooldown policy with:

```sh
./run.sh scripts/check-dependency-policy.py
```

Run all automated tests with:

```sh
scripts/run-tests.sh
```

Type-check all Python with:

```sh
./run.sh scripts/typecheck-python.py
```

### Windows NVIDIA GPU OCR

On Windows, the locked environment uses PaddlePaddle's CUDA 12.6 GPU wheel and selects GPU 0 automatically when the NVIDIA runtime is available. GPU support requires an x64 NVIDIA CUDA 12 runtime and an x64 cuDNN 9 runtime in the child-process `PATH`, in addition to a compatible NVIDIA driver.

The following archived installers were verified with the current PaddlePaddle wheel:

- [CUDA Toolkit 12.0 for Windows x86_64](https://developer.nvidia.com/cuda-12-0-0-download-archive?target_os=Windows&target_arch=x86_64&target_version=11&target_type=exe_local)
- [cuDNN 9.24 for Windows x86_64](https://developer.nvidia.com/cudnn-9-24-0-download-archive?target_os=Windows&target_arch=x86_64&target_version=11&target_type=exe_local)

Install the x64 variants, then generate the local ignored runtime configuration:

```powershell
& .\scripts\configure-paddle-cuda-environment.ps1
```

The script selects the newest valid installed CUDA Toolkit 12.x directory and cuDNN 9.x `bin\12.*\x64` directory, writes only its managed `PATH` entry to the ignored `.env.local` file, and verifies that PaddlePaddle sees a CUDA device. It preserves other `.env.local` entries, including provider credentials. Subsequent project commands use that file through the repository-root `run.ps1` or `run.sh` wrapper. CPU-only and non-Windows environments continue to use the standard CPU PaddlePaddle dependency.

The OCR task model and plugin contract are documented in [docs/ocr-provider-api.md](docs/ocr-provider-api.md). The text-replacement task model and plugin contract are documented in [docs/text-replacement-provider-api.md](docs/text-replacement-provider-api.md). The text-region-colour API is documented in [docs/text-region-colours-api.md](docs/text-region-colours-api.md), with its rationale and algorithm in [docs/text-region-colours-algorithm.md](docs/text-region-colours-algorithm.md). The Skia-backed in-place rendering API is documented in [docs/text-region-rendering-api.md](docs/text-region-rendering-api.md).

### Prepare OCR-evaluation inputs

Prepare local OCR inputs from the sample-data tree:

```sh
./run.sh scripts/prepare_ocr_evaluation_inputs.py
```

The generated outputs are ignored by Git and may contain confidential material. Do not add, stage, or commit them.

Only samples in a BCP 47 language directory are prepared. Place that directory directly below `sample-data/`, or one directory below it, for example `sample-data/ja/` or `sample-data/corpus/en-GB/`. The script mirrors eligible source paths and removes whole stale generated directories, while retaining extra files in generated directories that still correspond to source directories.

### Run OCR evaluations

Generate visual evaluation artifacts for every discovered OCR provider:

```sh
./run.sh scripts/run_ocr_evaluations.py
```

The command first prepares inputs from `sample-data/`. Results are written below `outputs/evaluations/ocr/output/<provider>/`. Each provider root contains the existing `index.html` OCR viewer, plus `text-replacement.html` for complete and clipped output from every local text-replacement provider. Successful OCR JSON results include their input `source_language`. tqdm renders one compact progress bar at a time for each language folder and its immediate child folders. A provider is skipped when its input checksum and generated viewers are current; delete its `.input.sha256` or a viewer to regenerate it.

### Run colour-estimation evaluations

Generate simple static HTML pages for the supplied colour-detection examples:

```sh
./run.sh scripts/run_colour_evaluations.py
```

The pages are written below `outputs/evaluations/color-detection-examples/`. Each page shows the existing padded text-region bitmap for every OCR region, alongside labelled colour swatches, confidence values, and background classification. These local generated artifacts are ignored by Git.

### Run text-replacement evaluations

Generate source-language-to-English visible replacement pages for every registered text-replacement provider:

```sh
./run.sh scripts/run_text_replacement_evaluations.py
```

Pages and their clipped rendered text images are written below `outputs/evaluations/text-replacement-examples/`. The evaluator uses the committed Noto Sans JP font asset and does not modify inputs.

## Candidate core technologies

Going to start with - **Offline:** PaddleOCR + Argos Translate.

### Offline / open-source

- **PaddleOCR - primary OCR**
  - Default OCR adapter.
  - Multilingual support, including Japanese, with text-region geometry.
  - [PaddleOCR](https://paddlepaddle.github.io/PaddleOCR/main/en/quick_start.html)

- **Tesseract - comparison OCR**
  - Use as a baseline/fallback in the OCR evaluation suite.
  - Apache-2.0 licensed; Japanese training data (`jpn`).
  - [Tesseract documentation](https://tesseract-ocr.github.io/tessdoc/)

- **Argos Translate - simple offline translation**
  - Local, open-source translation library with Japanese language packages.
  - Good first replacement-script implementation.
  - [Argos Translate](https://github.com/argosopentech/argos-translate/)

- **LibreTranslate - local translation API**
  - Self-hosted HTTP API built on Argos Translate.
  - Useful for replacement scripts that call a local service.
  - [Argos/LibreTranslate relationship](https://github.com/argosopentech/argos-translate/)

- **CTranslate2 + an open-licensed translation model - advanced local option**
  - Use later for faster local inference or user-selectable models.
  - Keep runtime and model separate; assess each model’s licence and Japanese quality.
  - [CTranslate2](https://github.com/OpenNMT/CTranslate2)

### Cloud APIs

- **Google Cloud Vision OCR + Cloud Translation - general cloud pair**
  - OCR polygons and language hints such as `ja`.
  - Formatted-document translation and glossaries.
  - [Vision OCR](https://docs.cloud.google.com/vision/docs/ocr)
  - [Cloud Translation documents](https://docs.cloud.google.com/translate/docs/advanced/translate-documents)

- **Azure Vision / Document Intelligence + Azure Document Translation - Microsoft-oriented pair**
  - Multilingual document OCR.
  - Batch translation of standalone images and embedded images in DOCX/PPTX.
  - [Azure Vision language support](https://learn.microsoft.com/en-us/azure/ai-services/computer-vision/language-support)
  - [Azure Document Translation](https://learn.microsoft.com/en-us/azure/ai-services/translator/document-translation/latest/overview)

- **DeepL API - translation-provider adapter**
  - Document translation for DOCX, PPTX, PDF, and image files.
  - Glossary support.
  - [DeepL document API](https://developers.deepl.com/api-reference/document/upload-and-translate-a-document)

- **OpenAI or Gemini multimodal models - optional context-aware adapter**
  - Use where surrounding image context improves translation.
  - Do not use as the default source of OCR coordinates or deterministic rendering.
