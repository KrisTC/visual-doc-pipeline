#!/usr/bin/env python3
"""Shared synthetic fixtures for folder-replacement regression tests."""

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


FONT_PATH = Path(__file__).parent / "assets" / "fonts" / "NotoSansJP[wght].ttf"


class _EmptyOcrProvider:
    supported_languages = frozenset({"en"})
    supports_local_contract_test = False
    skipped_local_contract_angles: frozenset[int] = frozenset()
    skipped_local_contract_cases: frozenset[LocalContractTestSkip] = frozenset()

    def recognize(self, request: OcrRequest) -> OcrResult:
        return OcrResult(())


class _CountingOcrProvider(_EmptyOcrProvider):
    def __init__(self) -> None:
        self.calls = 0

    def recognize(self, request: OcrRequest) -> OcrResult:
        self.calls += 1
        return OcrResult(())


class _FailingOcrProvider(_EmptyOcrProvider):
    def recognize(self, request: OcrRequest) -> OcrResult:
        raise RuntimeError("Synthetic OCR failed.") from ValueError(
            "Synthetic OCR chained detail must not be recorded."
        )


class _LowConfidenceOcrProvider(_EmptyOcrProvider):
    def recognize(self, request: OcrRequest) -> OcrResult:
        return OcrResult(
            (
                OcrText(
                    "skip me",
                    0.64,
                    BoundingPolygon(
                        (
                            PixelPoint(1, 1),
                            PixelPoint(20, 1),
                            PixelPoint(20, 10),
                            PixelPoint(1, 10),
                        )
                    ),
                ),
            )
        )


class _VectorOutlineOcrProvider(_EmptyOcrProvider):
    """Return one known 200-DPI polygon for a synthetic vector-only page."""

    def __init__(
        self, confidence: float = 0.99, polygon: BoundingPolygon | None = None
    ) -> None:
        self.confidence = confidence
        self.polygon = polygon or BoundingPolygon(
            (
                PixelPoint(50, 130),
                PixelPoint(230, 130),
                PixelPoint(230, 200),
                PixelPoint(50, 200),
            )
        )
        self.calls = 0

    def recognize(self, request: OcrRequest) -> OcrResult:
        self.calls += 1
        return OcrResult(
            (
                OcrText(
                    "outlined",
                    self.confidence,
                    self.polygon,
                ),
            )
        )


class _RecordingReplacementProvider:
    def __init__(self, filename: str | None = None, replacement_text: str | None = None) -> None:
        self.filename = filename
        self.replacement_text = replacement_text
        self.requests: list[TextReplacementRequest] = []

    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        self.requests.append(request)
        if request.is_filename and self.filename is not None:
            return TextReplacementResult(self.filename, 1.0)
        if request.is_filename:
            return TextReplacementResult(request.text, 1.0)
        return TextReplacementResult(self.replacement_text or "#" * len(request.text), 1.0)


def _synthetic_pdf_visual_region(text: str, font_resource_name: str) -> _PdfVisualRegion:
    """Construct a minimal fitted PDF region without a document-specific fixture."""
    identity = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    anchor = _PdfShownText(
        0, 0, text, (10.0, 10.0), (70.0, 10.0), (1.0, 0.0), (0.0, 1.0),
        1.0, 12.0, 0, ((), (), (), ()), identity, identity, identity,
        (NameObject(font_resource_name), FloatObject(12)), 0.0, 0.0, 1.0, 0.0, 0,
    )
    return _PdfVisualRegion(
        (0,), text, (1.0, 0.0), (0.0, 1.0), 10.0, 20.0, 60.0, 15.0,
        1.0, 12.0, "left", 0, identity, anchor,
    )


class _FailingReplacementProvider(_RecordingReplacementProvider):
    def replace(self, request: TextReplacementRequest) -> TextReplacementResult:
        self.requests.append(request)
        if request.is_filename:
            return TextReplacementResult(request.text, 1.0)
        raise RuntimeError("Synthetic text replacement failed.") from ValueError(
            "Synthetic chained detail must not be recorded."
        )


class _RecordedProgress:
    def __init__(self, total: int, label: str) -> None:
        self.total = total
        self.label = label
        self.postfixes: list[str] = []
        self.updates = 0
        self.closed = False

    def set_postfix_str(self, text: str) -> None:
        self.postfixes.append(text)

    def update(self, count: float | None = None) -> bool | None:
        self.updates += 1 if count is None else int(count)
        return None

    def close(self) -> None:
        self.closed = True




class FolderReplacementTestCase(unittest.TestCase):
    @staticmethod
    def _write_png(path: Path) -> None:
        Image.new("RGB", (30, 20), "white").save(path, "PNG")

    @staticmethod
    def _write_complete_docx(path: Path) -> None:
        """Write a complete synthetic DOCX package with a bounded text box."""
        with ZipFile(path, "w", ZIP_DEFLATED) as archive:
            archive.writestr(
                "[Content_Types].xml",
                b'''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/fontTable.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml"/>
</Types>''',
            )
            archive.writestr(
                "_rels/.rels",
                b'''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdOfficeDocument" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>''',
            )
            archive.writestr(
                "word/_rels/document.xml.rels",
                b'''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdExistingFontTable" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable" Target="fontTable.xml"/>
  <Relationship Id="rIdExistingSettings" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>
</Relationships>''',
            )
            archive.writestr(
                "word/settings.xml",
                b'''<?xml version="1.0" encoding="UTF-8"?>
<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:writeProtection/><w:zoom/><w:bordersDoNotSurroundHeader/>
</w:settings>''',
            )
            archive.writestr(
                "word/fontTable.xml",
                b'''<?xml version="1.0" encoding="UTF-8"?>
<w:fonts xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:font w:name="Noto Sans JP"><w:altName w:val="Synthetic Noto"/></w:font>
</w:fonts>''',
            )
            archive.writestr(
                "word/document.xml",
                b'''<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">
  <w:body>
    <w:p><w:r><w:t>Flow text</w:t></w:r></w:p>
    <w:p><w:r><w:drawing><wp:inline>
      <wp:extent cx="914400" cy="457200"/><wp:docPr id="1" name="Synthetic text box"/>
      <a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">
        <wps:wsp><wps:txbx><w:txbxContent>
          <w:p><w:r><w:rPr><w:b/><w:sz w:val="48"/></w:rPr><w:t>Bold text</w:t></w:r></w:p>
          <w:p><w:r><w:rPr><w:i/><w:sz w:val="48"/></w:rPr><w:t>Italic text</w:t></w:r></w:p>
          <w:p><w:r><w:rPr><w:sz w:val="48"/><w:u w:val="single"/></w:rPr><w:t>Underlined text</w:t></w:r></w:p>
        </w:txbxContent></wps:txbx></wps:wsp>
      </a:graphicData></a:graphic>
    </wp:inline></w:drawing></w:r></w:p>
    <w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>
  </w:body>
</w:document>''',
            )

    @staticmethod
    def _add_reachable_smartart_data_part(path: Path) -> None:
        """Add synthetic canonical SmartArt labels linked from the first slide."""
        content_types_namespace = "http://schemas.openxmlformats.org/package/2006/content-types"
        relationships_namespace = "http://schemas.openxmlformats.org/package/2006/relationships"
        with ZipFile(path) as source_archive:
            entries = source_archive.infolist()
            payloads = {
                entry.filename: source_archive.read(entry.filename) for entry in entries
            }
        relationships = ElementTree.fromstring(payloads["ppt/slides/_rels/slide1.xml.rels"])
        ElementTree.SubElement(
            relationships,
            f"{{{relationships_namespace}}}Relationship",
            {
                "Id": "rIdSmartArtData",
                "Type": (
                    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
                    "diagramData"
                ),
                "Target": "../diagrams/data1.xml",
            },
        )
        payloads["ppt/slides/_rels/slide1.xml.rels"] = ElementTree.tostring(
            relationships, encoding="utf-8", xml_declaration=True
        )
        content_types = ElementTree.fromstring(payloads["[Content_Types].xml"])
        ElementTree.SubElement(
            content_types,
            f"{{{content_types_namespace}}}Override",
            {
                "PartName": "/ppt/diagrams/data1.xml",
                "ContentType": "application/vnd.ms-office.drawingml.diagramData+xml",
            },
        )
        payloads["[Content_Types].xml"] = ElementTree.tostring(
            content_types, encoding="utf-8", xml_declaration=True
        )
        payloads["ppt/diagrams/data1.xml"] = b"""<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<dgm:dataModel xmlns:dgm=\"http://schemas.openxmlformats.org/drawingml/2006/diagram\" xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\">
  <dgm:ptLst>
    <dgm:pt modelId=\"node-1\"><dgm:t><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>SmartArt first</a:t></a:r></a:p></dgm:t></dgm:pt>
    <dgm:pt modelId=\"node-2\"><dgm:t><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>SmartArt second</a:t></a:r></a:p></dgm:t></dgm:pt>
  </dgm:ptLst>
  <dgm:cxnLst/>
  <dgm:bg/>
  <dgm:whole/>
</dgm:dataModel>"""
        temporary_path = path.with_name(f".{path.name}.smartart-fixture.tmp")
        with ZipFile(temporary_path, "w", ZIP_DEFLATED) as destination_archive:
            for entry in entries:
                destination_archive.writestr(entry, payloads[entry.filename])
            destination_archive.writestr("ppt/diagrams/data1.xml", payloads["ppt/diagrams/data1.xml"])
        temporary_path.replace(path)

    @staticmethod
    def _add_speaker_note_part(path: Path) -> None:
        """Add one reachable synthetic speaker-note part to a PPTX fixture."""
        content_types_namespace = "http://schemas.openxmlformats.org/package/2006/content-types"
        relationships_namespace = "http://schemas.openxmlformats.org/package/2006/relationships"
        with ZipFile(path) as source_archive:
            entries = source_archive.infolist()
            payloads = {
                entry.filename: source_archive.read(entry.filename) for entry in entries
            }
        relationships = ElementTree.fromstring(payloads["ppt/slides/_rels/slide1.xml.rels"])
        ElementTree.SubElement(
            relationships,
            f"{{{relationships_namespace}}}Relationship",
            {
                "Id": "rIdSpeakerNotes",
                "Type": (
                    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
                    "notesSlide"
                ),
                "Target": "../notesSlides/notesSlide1.xml",
            },
        )
        payloads["ppt/slides/_rels/slide1.xml.rels"] = ElementTree.tostring(
            relationships, encoding="utf-8", xml_declaration=True
        )
        content_types = ElementTree.fromstring(payloads["[Content_Types].xml"])
        ElementTree.SubElement(
            content_types,
            f"{{{content_types_namespace}}}Override",
            {
                "PartName": "/ppt/notesSlides/notesSlide1.xml",
                "ContentType": "application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml",
            },
        )
        payloads["[Content_Types].xml"] = ElementTree.tostring(
            content_types, encoding="utf-8", xml_declaration=True
        )
        note_name = "ppt/notesSlides/notesSlide1.xml"
        payloads[note_name] = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:notes xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree>
    <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>
    <p:sp><p:nvSpPr><p:cNvPr id="2" name="Notes Placeholder"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr/>
      <p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>Speaker note source</a:t></a:r></a:p></p:txBody>
    </p:sp>
  </p:spTree></p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr><p:extLst><p:ext uri="keep-note-extension"/></p:extLst>
</p:notes>'''
        temporary_path = path.with_name(f".{path.name}.notes-fixture.tmp")
        with ZipFile(temporary_path, "w", ZIP_DEFLATED) as destination_archive:
            for entry in entries:
                destination_archive.writestr(entry, payloads[entry.filename])
            destination_archive.writestr(note_name, payloads[note_name])
        temporary_path.replace(path)

    def _assert_drawingml_paragraph_property_order(self, data: bytes) -> None:
        """Verify the schema order that PowerPoint requires for ``a:pPr`` children."""
        namespace = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
        order = (
            "lnSpc",
            "spcBef",
            "spcAft",
            "buClrTx",
            "buClr",
            "buSzTx",
            "buSzPct",
            "buSzPts",
            "buFontTx",
            "buFont",
            "buNone",
            "buAutoNum",
            "buChar",
            "buBlip",
            "tabLst",
            "defRPr",
            "extLst",
        )
        ranks = {name: index for index, name in enumerate(order)}
        for properties in ElementTree.fromstring(data).iter(f"{namespace}pPr"):
            child_names = [child.tag.removeprefix(namespace) for child in properties]
            self.assertEqual(
                sorted(child_names, key=lambda name: ranks.get(name, len(ranks))),
                child_names,
            )

    def _assert_word_run_property_order(self, root: ElementTree.Element) -> None:
        """Verify the WordprocessingML ``CT_RPr`` child order."""
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        order = (
            "rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps",
            "strike", "dstrike", "outline", "shadow", "emboss", "imprint", "noProof",
            "snapToGrid", "vanish", "webHidden", "color", "spacing", "w", "kern",
            "position", "sz", "szCs", "highlight", "u", "effect", "bdr", "shd",
            "fitText", "vertAlign", "rtl", "cs", "em", "lang", "eastAsianLayout",
            "specVanish", "oMath",
        )
        ranks = {name: index for index, name in enumerate(order)}
        for properties in root.iter(f"{namespace}rPr"):
            child_names = [child.tag.removeprefix(namespace) for child in properties]
            self.assertEqual(
                sorted(child_names, key=lambda name: ranks.get(name, len(ranks))),
                child_names,
            )

    @staticmethod
    def _sfnt_font_metadata(data: bytes) -> dict[str, dict[str, str]]:
        table_count = int.from_bytes(data[4:6], "big")
        tables = {
            data[12 + index * 16:16 + index * 16].decode("ascii"):
            int.from_bytes(data[20 + index * 16:24 + index * 16], "big")
            for index in range(table_count)
        }
        os2, post = tables["OS/2"], tables["post"]
        family_class = int.from_bytes(data[os2 + 30:os2 + 32], "big") >> 8
        family = {**{value: "roman" for value in range(1, 8)}, 8: "swiss", 9: "decorative", 10: "script"}.get(family_class, "auto")
        code_pages = int.from_bytes(data[os2 + 78:os2 + 82], "big")
        charset = next(
            (value for bit, value in ((17, "80"), (18, "81"), (19, "82"), (20, "86"), (21, "88"), (0, "00")) if code_pages & (1 << bit)),
            "00",
        )
        return {
            "panose1": {"val": data[os2 + 32:os2 + 42].hex().upper()},
            "charset": {"val": charset},
            "family": {"val": family},
            "pitch": {"val": "fixed" if int.from_bytes(data[post + 12:post + 16], "big") else "variable"},
            "sig": {
                "usb0": data[os2 + 42:os2 + 46].hex().upper(),
                "usb1": data[os2 + 46:os2 + 50].hex().upper(),
                "usb2": data[os2 + 50:os2 + 54].hex().upper(),
                "usb3": data[os2 + 54:os2 + 58].hex().upper(),
                "csb0": data[os2 + 78:os2 + 82].hex().upper(),
                "csb1": data[os2 + 82:os2 + 86].hex().upper(),
            },
        }

    def _assert_valid_drawingml_font_sizes(self, data: bytes) -> None:
        """Verify explicit run sizes stay within the OOXML DrawingML range."""
        namespace = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
        run_tags = {f"{namespace}rPr", f"{namespace}endParaRPr", f"{namespace}defRPr"}
        for properties in ElementTree.fromstring(data).iter():
            if properties.tag not in run_tags or "sz" not in properties.attrib:
                continue
            self.assertGreaterEqual(int(properties.attrib["sz"]), 100)
            self.assertLessEqual(int(properties.attrib["sz"]), 400_000)

    def _pdf_generated_replacement_font_size(self, source: Path) -> float:
        """Return the largest fitted portable-output font size in one PDF."""
        reader = PdfReader(source)
        stream = ContentStream(reader.pages[0].get_contents(), reader)
        active_font = ""
        sizes: list[float] = []
        for operands, operator in stream.operations:
            if operator == b"Tf":
                active_font = str(operands[0])
                if active_font == "/PipelineNoto":
                    sizes.append(float(operands[1]))
        self.assertTrue(sizes)
        return max(sizes)

    def _run(
        self,
        input_root: Path,
        output_root: Path,
        ocr_provider: _EmptyOcrProvider,
        replacement_provider: TextReplacementProvider,
        *,
        show_progress: bool = False,
        progress_factory: ProgressFactory | None = None,
        document_text_layout: str = "preserve-source-formatting",
        include_patterns: tuple[str, ...] = (),
        diagnostics_enabled: bool = False,
    ) -> FolderReplacementResult:
        typeface = skia.Typeface.MakeFromFile(str(FONT_PATH))
        if typeface is None:
            self.fail("Could not load test typeface.")
        return replace_input_folder(
            input_root,
            output_root,
            ocr_provider=ocr_provider,
            text_replacement_provider=replacement_provider,
            source_language="en",
            target_language="en",
            typeface=typeface,
            document_text_layout=document_text_layout,
            include_patterns=include_patterns,
            diagnostics_enabled=diagnostics_enabled,
            show_progress=show_progress,
            progress_factory=progress_factory,
        )
