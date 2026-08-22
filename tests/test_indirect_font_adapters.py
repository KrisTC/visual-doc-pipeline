"""Synthetic indirect-font adapter coverage for DOCX, XLSX, and SVG."""

from __future__ import annotations

import unittest
import xml.etree.ElementTree as ElementTree

from pipeline.folder_replacement.docx import _DocxFontResolver, _W
from pipeline.folder_replacement.xlsx import _Styles
from pipeline.pptx_theme_fonts import PptxThemeFonts
from pipeline.vector_text.svg import _SvgCss, _css_font_families


_THEME = PptxThemeFonts(
    {("major", "latin"): "Major Latin", ("major", "eastAsian"): "Major East Asian", ("major", "complex"): "Major Complex",
     ("minor", "latin"): "Minor Latin", ("minor", "eastAsian"): "Minor East Asian", ("minor", "complex"): "Minor Complex"},
    {},
)


class IndirectFontAdapterTests(unittest.TestCase):
    # Verifies FR-2026-08-22-11.
    def test_docx_resolves_style_theme_references_but_retains_the_original_token(self) -> None:
        drawing = "http://schemas.openxmlformats.org/drawingml/2006/main"
        package = "http://schemas.openxmlformats.org/package/2006/relationships"
        office = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        word = _W
        parts = {
            "word/styles.xml": f'''<w:styles xmlns:w="{word}"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:asciiTheme="minorHAnsi"/></w:rPr></w:rPrDefault></w:docDefaults><w:style w:type="paragraph" w:styleId="P"><w:rPr><w:rFonts w:eastAsiaTheme="majorEastAsia"/></w:rPr></w:style></w:styles>'''.encode(),
            "word/_rels/document.xml.rels": f'''<Relationships xmlns="{package}"><Relationship Id="rId1" Type="{office}/theme" Target="theme/theme1.xml"/></Relationships>'''.encode(),
            "word/theme/theme1.xml": _theme_xml(drawing),
        }
        resolver = _DocxFontResolver.from_parts(parts)
        paragraph = ElementTree.fromstring(f'<w:p xmlns:w="{word}"><w:pPr><w:pStyle w:val="P"/></w:pPr><w:r><w:t>A日</w:t></w:r></w:p>')
        run = next(item for item in paragraph if item.tag.endswith("}r"))
        references = resolver.references_for(run, paragraph, "A日")

        self.assertEqual(["minorHAnsi", "majorEastAsia"], [item.original_family for item in references])
        self.assertEqual(["Minor Latin", "Major East Asian"], [item.resolved_family for item in references])

    # Verifies FR-2026-08-22-12.
    def test_xlsx_scheme_resolves_only_when_no_direct_name_is_present(self) -> None:
        spreadsheet = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        styles = f'''<styleSheet xmlns="{spreadsheet}"><fonts count="2"><font><scheme val="major"/></font><font><name val="Direct"/><scheme val="minor"/></font></fonts><cellXfs count="2"><xf fontId="0"/><xf fontId="1"/></cellXfs></styleSheet>'''.encode()
        style_adapter = _Styles(styles, _THEME)
        major_cell = ElementTree.fromstring(f'<c xmlns="{spreadsheet}" s="0"/>')
        direct_cell = ElementTree.fromstring(f'<c xmlns="{spreadsheet}" s="1"/>')

        self.assertEqual("major", style_adapter.run_for(major_cell).source_typefaces[0].original_family)
        self.assertEqual("Major Latin", style_adapter.run_for(major_cell).source_typefaces[0].resolved_family)
        self.assertEqual("Direct", style_adapter.run_for(direct_cell).font_family)
        self.assertFalse(style_adapter.run_for(direct_cell).source_typefaces)

    # Verifies FR-2026-08-22-13.
    def test_svg_css_inherits_supported_selectors_and_preserves_stack_order(self) -> None:
        root = ElementTree.fromstring('''<svg><style>g.note text {font-family: "First", "Second", serif; font-style: italic} #target {font-weight: 700}</style><g class="note"><text id="target">Text</text></g></svg>''')
        parents = {child: parent for parent in root.iter() for child in parent}
        text = next(item for item in root.iter() if item.tag == "text")
        css = _SvgCss(root, parents)

        self.assertEqual('"First", "Second", serif', css.property_for(text, "font-family"))
        self.assertEqual("italic", css.property_for(text, "font-style"))
        self.assertEqual("700", css.property_for(text, "font-weight"))
        self.assertEqual(("First", "Second", "serif"), _css_font_families(css.property_for(text, "font-family")))
        self.assertEqual((), _css_font_families("var(--font)"))


def _theme_xml(drawing: str) -> bytes:
    return f'''<a:theme xmlns:a="{drawing}"><a:themeElements><a:fontScheme name="x"><a:majorFont><a:latin typeface="Major Latin"/><a:ea typeface="Major East Asian"/><a:cs typeface="Major Complex"/></a:majorFont><a:minorFont><a:latin typeface="Minor Latin"/><a:ea typeface="Minor East Asian"/><a:cs typeface="Minor Complex"/></a:minorFont></a:fontScheme></a:themeElements></a:theme>'''.encode()


if __name__ == "__main__":
    unittest.main()
