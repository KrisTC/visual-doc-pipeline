"""Synthetic PPTX relationship and theme-font tests."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

from pipeline.pptx_theme_fonts import pptx_themes_by_slide


class PptxThemeFontsTests(unittest.TestCase):
    # Verifies FR-2026-08-22-10.
    def test_resolves_all_alias_slots_from_the_slide_reachable_theme(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "synthetic.pptx"
            _write_package(path)
            theme = pptx_themes_by_slide(path)[0]

            assert theme is not None
            self.assertEqual("Major Latin", theme.resolve("+mj-lt", "latin"))
            self.assertEqual("Major East Asian", theme.resolve("+mj-ea", "eastAsian"))
            self.assertEqual("Major Complex", theme.resolve("+mj-cs", "complex"))
            self.assertEqual("Minor Latin", theme.resolve("+mn-lt", "latin"))
            self.assertEqual("Minor East Asian", theme.resolve("+mn-ea", "eastAsian"))
            self.assertEqual("Minor Complex", theme.resolve("+mn-cs", "complex"))
            self.assertEqual("Direct Face", theme.resolve("Direct Face", "latin"))


def _write_package(path: Path) -> None:
    relationships = "http://schemas.openxmlformats.org/package/2006/relationships"
    office = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    drawing = "http://schemas.openxmlformats.org/drawingml/2006/main"
    presentation = "http://schemas.openxmlformats.org/presentationml/2006/main"
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("_rels/.rels", f'''<Relationships xmlns="{relationships}">
          <Relationship Id="rId1" Type="{office}/officeDocument" Target="ppt/presentation.xml"/>
        </Relationships>''')
        archive.writestr("ppt/presentation.xml", f'''<p:presentation xmlns:p="{presentation}" xmlns:r="{office}">
          <p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst></p:presentation>''')
        archive.writestr("ppt/_rels/presentation.xml.rels", f'''<Relationships xmlns="{relationships}">
          <Relationship Id="rId1" Type="{office}/slide" Target="slides/slide1.xml"/>
        </Relationships>''')
        archive.writestr("ppt/slides/slide1.xml", "<slide/>")
        archive.writestr("ppt/slides/_rels/slide1.xml.rels", f'''<Relationships xmlns="{relationships}">
          <Relationship Id="rId1" Type="{office}/slideLayout" Target="../slideLayouts/slideLayout9.xml"/>
        </Relationships>''')
        archive.writestr("ppt/slideLayouts/slideLayout9.xml", "<layout/>")
        archive.writestr("ppt/slideLayouts/_rels/slideLayout9.xml.rels", f'''<Relationships xmlns="{relationships}">
          <Relationship Id="rId1" Type="{office}/slideMaster" Target="../slideMasters/slideMaster7.xml"/>
        </Relationships>''')
        archive.writestr("ppt/slideMasters/slideMaster7.xml", "<master/>")
        archive.writestr("ppt/slideMasters/_rels/slideMaster7.xml.rels", f'''<Relationships xmlns="{relationships}">
          <Relationship Id="rId1" Type="{office}/theme" Target="../themes/custom.xml"/>
        </Relationships>''')
        archive.writestr("ppt/themes/custom.xml", f'''<a:theme xmlns:a="{drawing}"><a:themeElements><a:fontScheme name="x">
          <a:majorFont><a:latin typeface="Major Latin"/><a:ea typeface="Major East Asian"/><a:cs typeface="Major Complex"/></a:majorFont>
          <a:minorFont><a:latin typeface="Minor Latin"/><a:ea typeface="Minor East Asian"/><a:cs typeface="Minor Complex"/></a:minorFont>
        </a:fontScheme></a:themeElements></a:theme>''')


if __name__ == "__main__":
    unittest.main()
