#!/usr/bin/env python3
"""Synthetic regression tests for DOCX folder replacement."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import BytesIO, StringIO
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from typing import cast
import unittest
from unittest.mock import patch
from uuid import UUID
import xml.etree.ElementTree as ElementTree
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image
from docx import Document
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, Protection
from openpyxl.worksheet.table import Table
from pptx import Presentation
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE
from pptx.oxml import parse_xml
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt
# pypdf does not publish PEP 561 metadata for its generic object model.
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, ByteStringObject, ContentStream, DecodedStreamObject, DictionaryObject, FloatObject, NameObject, NumberObject, TextStringObject
# skia-python does not publish PEP 561 stubs; this is the native rendering boundary.
import skia  # type: ignore[import-not-found]

from pipeline.folder_replacement import (
    FolderReplacementResult,
    parse_include_patterns,
    replace_input_folder,
)
from pipeline.folder_replacement.processor import ProgressFactory, ProgressReporter
from pipeline.folder_replacement.docx import _docx_ocr_backgrounds
from pipeline.folder_replacement.pptx import _pptx_ocr_backgrounds
from pipeline.folder_replacement.pdf import (
    _PdfPaintSpan,
    _PdfShownText,
    _PdfVisualRegion,
    _PdfReplacementSerializationError,
    _pdf_apply_paint_span_bullet_overrides,
    _pdf_apply_legacy_bullet_override,
    _pdf_content_has_annotations,
    _pdf_decode_composite_bytes,
    _pdf_expansion_geometry_is_known,
    _pdf_fitted_region_operations,
    _pdf_is_candidate_bullet_error,
    _pdf_text_advance,
)
from pipeline.folder_replacement.xlsx import _replace_drawing
from pipeline.folder_replacement.docx import _validate_docx_embedded_fonts
from pipeline.bounded_text_layout import (
    BoundedTextBox,
    BoundedTextParagraph,
    BoundedTextRun,
    PortableTextUnsupportedError,
    noto_typefaces,
)
from pipeline.portable_bullet_overrides import LegacyBulletOverride
from pipeline.portable_fonts import static_noto_bytes
from pipeline.ocr import BoundingPolygon, OcrRequest, OcrResult, OcrText, PixelPoint
from pipeline.ocr.provider import LocalContractTestSkip
from pipeline.text_replacement import (
    TextReplacementProvider,
    TextReplacementRequest,
    TextReplacementResult,
)
from pipeline.text_replacement_plugins.character_mask import CharacterMaskProvider



from folder_replacement_test_support import (
    FolderReplacementTestCase,
    _CountingOcrProvider,
    _EmptyOcrProvider,
    _FailingOcrProvider,
    _FailingReplacementProvider,
    _LowConfidenceOcrProvider,
    _RecordedProgress,
    _RecordingReplacementProvider,
    _VectorOutlineOcrProvider,
    _synthetic_pdf_visual_region,
)

class FolderReplacementDocxTests(FolderReplacementTestCase):
    # Verifies FR-2026-08-27-01.
    def test_uses_a_direct_document_background_for_embedded_word_image_ocr(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            document = Path(temporary_directory) / "input.docx"
            with ZipFile(document, "w", ZIP_DEFLATED) as archive:
                archive.writestr(
                    "word/document.xml",
                    """<?xml version=\"1.0\"?>
                    <w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">
                      <w:background w:color=\"102030\"/>
                    </w:document>""",
                )
                archive.writestr("word/media/image1.png", b"synthetic")

            self.assertEqual({"word/media/image1.png": (16, 32, 48)}, _docx_ocr_backgrounds(document))

    # Verifies FR-2026-08-04-07 and FR-2026-08-22-03.
    def test_docx_basic_layout_fits_drawing_text_and_embeds_conformant_fonts(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            source = input_root / "document.docx"
            self._write_complete_docx(source)
            self._run(
                input_root, output_root, _EmptyOcrProvider(),
                _RecordingReplacementProvider(replacement_text="Long replacement text " * 20),
                document_text_layout="preserve-basic-layout",
            )
            output = output_root / "document.docx"
            Document(str(output))
            with ZipFile(output) as archive:
                data = archive.read("word/document.xml")
                font_table = ElementTree.fromstring(archive.read("word/fontTable.xml"))
                font_relationships = ElementTree.fromstring(
                    archive.read("word/_rels/fontTable.xml.rels")
                )
                content_types = ElementTree.fromstring(archive.read("[Content_Types].xml"))
                settings = ElementTree.fromstring(archive.read("word/settings.xml"))
                self._assert_word_run_property_order(ElementTree.fromstring(data))
                targets = {item.get("Id"): item.get("Target") for item in font_relationships}
                embedded_font_ids: set[str] = set()
                namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
                relationships_namespace = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
                font_sources = {
                    "Noto Sans JP": "sans-serif",
                    "Noto Serif JP": "serif",
                    "Noto Sans Mono": "fixed-width",
                }
                for family, classification in font_sources.items():
                    entries = [
                        item for item in font_table.findall(f"{namespace}font")
                        if item.get(f"{namespace}name") == family
                    ]
                    self.assertEqual(1, len(entries))
                    if family != "Noto Sans JP":
                        expected_metadata = self._sfnt_font_metadata(
                            static_noto_bytes(classification, False)
                        )
                        metadata_names = [
                            child.tag.rsplit("}", 1)[-1]
                            for child in entries[0]
                        ]
                        self.assertEqual(
                            [
                                "panose1", "charset", "family", "pitch", "sig",
                                "embedRegular", "embedBold",
                            ],
                            metadata_names,
                        )
                        for child in entries[0][:5]:
                            self.assertEqual(
                                expected_metadata[child.tag.rsplit("}", 1)[-1]],
                                {
                                    key.rsplit("}", 1)[-1]: value
                                    for key, value in child.attrib.items()
                                },
                            )
                    for style in ("embedRegular", "embedBold"):
                        embedding = entries[0].find(f"{namespace}{style}")
                        self.assertIsNotNone(embedding)
                        assert embedding is not None
                        relationship_id = embedding.get(f"{relationships_namespace}id")
                        font_key = embedding.get(f"{namespace}fontKey")
                        self.assertIsNotNone(relationship_id)
                        self.assertIsNotNone(font_key)
                        assert relationship_id is not None and font_key is not None
                        self.assertNotIn(relationship_id, embedded_font_ids)
                        embedded_font_ids.add(relationship_id)
                        target = targets[relationship_id]
                        recovered = bytearray(archive.read(f"word/{target}"))
                        standard_key = UUID(font_key.strip("{}")).bytes[::-1]
                        for offset in range(min(32, len(recovered))):
                            recovered[offset] ^= standard_key[offset % 16]
                        self.assertEqual(
                            bytes(recovered),
                            static_noto_bytes(classification, style == "embedBold"),
                        )
                        self.assertIsNotNone(
                            skia.Typeface.MakeFromData(skia.Data.MakeWithCopy(bytes(recovered)))
                        )
                self.assertEqual(6, len(embedded_font_ids))
                self.assertEqual(
                    1,
                    sum(item.get("Extension") == "odttf" for item in content_types),
                )
                self.assertEqual(
                    1,
                    sum(item.get("PartName") == "/word/fontTable.xml" for item in content_types),
                )
                content_type_names = [item.tag.rsplit("}", 1)[-1] for item in content_types]
                first_override = content_type_names.index("Override")
                self.assertNotIn("Default", content_type_names[first_override:])
                setting_names = [item.tag.rsplit("}", 1)[-1] for item in settings]
                self.assertEqual(
                    [
                        "writeProtection", "zoom", "embedTrueTypeFonts",
                        "bordersDoNotSurroundHeader",
                    ],
                    setting_names,
                )
            self.assertIn(b"Noto Sans JP", data)
            self.assertIn(b"Long replacement text", data)
            generated_property_names = {
                child.tag.rsplit("}", 1)[-1]
                for properties in ElementTree.fromstring(data).findall(
                    ".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}txbxContent"
                    "//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}rPr"
                )
                for child in properties
            }
            self.assertTrue({"b", "i", "u"}.issubset(generated_property_names))

            corrupted = root / "corrupted.docx"
            with ZipFile(output) as source_archive, ZipFile(corrupted, "w", ZIP_DEFLATED) as corrupted_archive:
                corrupted_part = "word/fonts/pipeline-sans-serif-regular.odttf"
                for entry in source_archive.infolist():
                    payload = source_archive.read(entry.filename)
                    if entry.filename == corrupted_part:
                        payload = b"bad font" + payload[8:]
                    corrupted_archive.writestr(entry, payload)
            with ZipFile(corrupted) as corrupted_archive:
                parts = {
                    entry.filename: corrupted_archive.read(entry.filename)
                    for entry in corrupted_archive.infolist()
                }
            with self.assertRaisesRegex(ValueError, "not a loadable OpenType font"):
                _validate_docx_embedded_fonts(parts)

            missing_setting_parts = parts.copy()
            settings = ElementTree.fromstring(missing_setting_parts["word/settings.xml"])
            setting = settings.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}embedTrueTypeFonts")
            self.assertIsNotNone(setting)
            assert setting is not None
            settings.remove(setting)
            missing_setting_parts["word/settings.xml"] = ElementTree.tostring(settings)
            with self.assertRaisesRegex(ValueError, "embedded-font setting is missing"):
                _validate_docx_embedded_fonts(missing_setting_parts)

            misplaced_setting_parts = parts.copy()
            settings = ElementTree.fromstring(misplaced_setting_parts["word/settings.xml"])
            setting = settings.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}embedTrueTypeFonts")
            self.assertIsNotNone(setting)
            assert setting is not None
            settings.remove(setting)
            settings.append(setting)
            misplaced_setting_parts["word/settings.xml"] = ElementTree.tostring(settings)
            with self.assertRaisesRegex(ValueError, "not in CT_Settings order"):
                _validate_docx_embedded_fonts(misplaced_setting_parts)

    # Verifies FR-2026-08-28-03.
    def test_word_failure_records_safe_native_text_context_and_continues(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            with ZipFile(input_root / "document.docx", "w", ZIP_DEFLATED) as archive:
                archive.writestr(
                    "word/document.xml",
                    """<?xml version="1.0"?>
                    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                      <w:body><w:p><w:r><w:t>synthetic request text</w:t></w:r></w:p></w:body>
                    </w:document>""",
                )
            self._write_png(input_root / "good.png")

            result = self._run(
                input_root,
                output_root,
                _EmptyOcrProvider(),
                _FailingReplacementProvider(),
                diagnostics_enabled=True,
            )

            self.assertEqual(1, result.failed_files)
            self.assertEqual(1, result.processed_files)
            self.assertFalse((output_root / "document.docx").exists())
            self.assertTrue((output_root / "good.png").exists())
            diagnostic = json.loads(
                (output_root / "document.docx.diagnostics.json").read_text(encoding="utf-8")
            )
            entry = diagnostic["entries"][0]
            self.assertEqual("RuntimeError", entry["exception_type"])
            self.assertEqual(["ValueError"], entry["exception_cause_types"])
            self.assertEqual(
                {
                    "stage": "native_xml",
                    "container_kind": "office_xml",
                    "operation": "text_replacement",
                    "location": {"package_part": "word/document.xml"},
                    "request": {
                        "kind": "text_replacement",
                        "source_language": "en",
                        "target_language": "en",
                        "is_filename": False,
                        "input_character_count": 22,
                    },
                },
                entry["failure_context"],
            )
            serialized = json.dumps(diagnostic)
            self.assertNotIn("synthetic request text", serialized)
            self.assertNotIn("Synthetic chained detail", serialized)

    # Verifies FR-2026-08-28-03.
    def test_word_embedded_image_failure_records_safe_ocr_context(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_root = root / "input"
            output_root = root / "output"
            input_root.mkdir()
            image_bytes = BytesIO()
            Image.new("RGB", (7, 5), (16, 32, 48)).save(image_bytes, format="PNG")
            with ZipFile(input_root / "document.docx", "w", ZIP_DEFLATED) as archive:
                archive.writestr(
                    "word/document.xml",
                    """<?xml version="1.0"?>
                    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>""",
                )
                archive.writestr("word/media/image1.png", image_bytes.getvalue())

            result = self._run(
                input_root,
                output_root,
                _FailingOcrProvider(),
                _RecordingReplacementProvider(),
                diagnostics_enabled=True,
            )

            self.assertEqual(1, result.failed_files)
            entry = json.loads(
                (output_root / "document.docx.diagnostics.json").read_text(encoding="utf-8")
            )["entries"][0]
            self.assertEqual("RuntimeError", entry["exception_type"])
            self.assertEqual(["ValueError"], entry["exception_cause_types"])
            self.assertEqual(
                {
                    "stage": "embedded_bitmap",
                    "container_kind": "embedded_bitmap",
                    "operation": "ocr",
                    "location": {
                        "package_part": "word/media/image1.png",
                        "item_index": 1,
                    },
                    "request": {
                        "kind": "ocr",
                        "language": "en",
                        "image_width": 7,
                        "image_height": 5,
                        "image_mode": "RGB",
                    },
                },
                entry["failure_context"],
            )
            self.assertNotIn("Synthetic OCR chained detail", json.dumps(entry))



if __name__ == "__main__":
    unittest.main()
