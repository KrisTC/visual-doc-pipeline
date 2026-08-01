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

This project uses Python 3.14.6 and [uv](https://docs.astral.sh/uv/). Create or update the local environment only from the committed lockfile:

```sh
uv sync --locked
```

Check the dependency source and cooldown policy with:

```sh
.venv/bin/python scripts/check-dependency-policy.py
```

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
