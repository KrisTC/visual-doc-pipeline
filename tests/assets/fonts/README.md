# OCR contract-test fonts

These repository-owned assets make synthetic English and Japanese OCR tests, plus the local Skia text-replacement evaluator, independent of the operating system's installed fonts and network access.

| Asset | Face used by tests | Upstream source | Upstream revision | SHA-256 |
|---|---|---|---|---|
| `NotoSansJP[wght].ttf` | Noto Sans JP Regular; Noto Sans JP Bold | [Google Fonts source](https://github.com/google/fonts/blob/main/ofl/notosansjp/NotoSansJP%5Bwght%5D.ttf) | Noto CJK `523d033d6cb47f4a80c58a35753646f5c3608a78` | `c2f3b4d463500a2ddcd3849cded1fceeb9fd6d1c32e6cbecd568453ba50fc68f` |
| `NotoSerifJP[wght].ttf` | Noto Serif JP Regular | [Google Fonts source](https://github.com/google/fonts/blob/main/ofl/notoserifjp/NotoSerifJP%5Bwght%5D.ttf) | Noto CJK `985fa52c81c1d6692ccdd82bc3656e8fb932fd89` | `2fd527ba12b6a44ec30d796d633360da0aeba6c5d4af1304ce12bb4dc15a7dfc` |
| `OFL.txt` | License | [Google Fonts source](https://github.com/google/fonts/blob/main/ofl/notosansjp/OFL.txt) | Noto CJK `523d033d6cb47f4a80c58a35753646f5c3608a78` | `1c05c68c34f9708415aada51f17e1b0092d2cea709bf4a94cd38114f9e73d7d9` |

The font files are licensed under the [SIL Open Font License, Version 1.1](OFL.txt). The local text-replacement evaluator loads `NotoSansJP[wght].ttf`; other product code does not load these assets by default.
