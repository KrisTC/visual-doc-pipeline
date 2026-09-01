# Requirements Index

The files in this directory are the authoritative requirements. Requirement IDs are immutable and may be referenced across files.

| Task scope | Read first |
|---|---|
| Shared pipeline, CLI, layout, cache, diagnostics, or development scenarios | `general-requirements.md` |
| Raster images, OCR providers, OCR evaluation, or replacement-image rendering | `raster-ocr-requirements.md` |
| Text-replacement provider contract or deterministic replacement-provider test support | `text-replacement-requirements.md` |
| Google Cloud Translation provider or its local configuration | `google-cloud-translation-requirements.md` |
| Argos Translate provider | `argos-translate-requirements.md` |
| PDF | `pdf-requirements.md` |
| PowerPoint / PPTX | `powerpoint-requirements.md` |
| Word / DOCX | `word-requirements.md` |
| Excel / XLSX | `excel-requirements.md` |
| SVG, EMF, WMF, or other vector graphics | `vector-requirements.md` |
| Dependency, credential, remote-data, or local-persistence security | `security-requirements.md` |
| Tools, dependencies, test runners, typing, or shared implementation structure | `technical-requirements.md` |

For a task, read the routed file, `general-requirements.md` when the task uses the common pipeline, and every explicitly related requirement. Read `security-requirements.md` and `technical-requirements.md` whenever the routed requirement references them or the change affects their scope. For a multi-format task, read every relevant format file.

A requirement belongs in the file that owns its primary behaviour. Shared requirements belong in `general-requirements.md`; a format-specific rule shall reference shared requirements and state only its additional or differing behaviour. Do not duplicate an unchanged shared contract.

New requirements use the existing metadata fields: Title, Owner, Status, Source, Date Added, and Related Requirements. Put mandatory behaviour in **Description**. Use **Rationale** only for concise decision context. Use **Notes** only for non-normative context; put test obligations in Description or a concise Verification subsection.

`feature-requirements.md` is a migration pointer. Superseded requirements are removed from this directory; use Git history when historical context is necessary.
