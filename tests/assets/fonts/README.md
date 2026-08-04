# OCR contract-test fonts

These repository-owned assets make synthetic English and Japanese OCR tests, plus the local Skia text-replacement evaluator, independent of the operating system's installed fonts and network access.

| Asset | Face used by tests | Upstream source | Upstream revision | SHA-256 |
|---|---|---|---|---|
| `NotoSansJP[wght].ttf` | Noto Sans JP Regular; Noto Sans JP Bold | [Google Fonts source](https://github.com/google/fonts/blob/main/ofl/notosansjp/NotoSansJP%5Bwght%5D.ttf) | Noto CJK `523d033d6cb47f4a80c58a35753646f5c3608a78` | `c2f3b4d463500a2ddcd3849cded1fceeb9fd6d1c32e6cbecd568453ba50fc68f` |
| `NotoSerifJP[wght].ttf` | Noto Serif JP Regular | [Google Fonts source](https://github.com/google/fonts/blob/main/ofl/notoserifjp/NotoSerifJP%5Bwght%5D.ttf) | Noto CJK `985fa52c81c1d6692ccdd82bc3656e8fb932fd89` | `2fd527ba12b6a44ec30d796d633360da0aeba6c5d4af1304ce12bb4dc15a7dfc` |
| `NotoSansMono[wdth,wght].ttf` | Noto Sans Mono | [Google Fonts source](https://github.com/google/fonts/blob/2796410152d4f9524b68ed46e69c1b60f8e0f7c3/ofl/notosansmono/NotoSansMono%5Bwdth%2Cwght%5D.ttf) | Google Fonts `2796410152d4f9524b68ed46e69c1b60f8e0f7c3` | `2cb2adb378a8f574213e23df697050b83c54c27df465a2015552740b2769a081` |
| `NotoSansCJKjp-Regular.ttf` | Noto Sans CJK JP Regular static embedding face | [Noto Sans CJK JP source](https://github.com/minoryorg/Noto-Sans-CJK-JP/blob/master/fonts/NotoSansCJKjp-Regular.ttf) | Noto Sans CJK JP `7fbcb560ac433b37f7f0e65507e78924b717f7a7` | `1eb44b7c923c0830ef19321601ad37037792b96ffcc289478dc49c5ce83a8ce6` |
| `NotoSansCJKjp-Bold.ttf` | Noto Sans CJK JP Bold static embedding face | [Noto Sans CJK JP source](https://github.com/minoryorg/Noto-Sans-CJK-JP/blob/master/fonts/NotoSansCJKjp-Bold.ttf) | Noto Sans CJK JP `7fbcb560ac433b37f7f0e65507e78924b717f7a7` | `ceb1e50b3c70617e699f847eb49bbf3602315aa56371475262e8923be1f921fb` |
| `NotoSansJP-Regular.ttf` | Noto Sans JP Regular static embedding face | instantiated from `NotoSansJP[wght].ttf` at `wght=400` with FontTools 4.62.0 | Google Fonts source revision above | `1727669567f67a2492d696a6b6ec1370705693d6995bfcf3248fad4849a126fe` |
| `NotoSansJP-Bold.ttf` | Noto Sans JP Bold static embedding face | instantiated from `NotoSansJP[wght].ttf` at `wght=700` with FontTools 4.62.0 | Google Fonts source revision above | `58fde701ae4bc0903cfdb8f6b618a21eaaab356bbb07f1292aedc6e7729cefc7` |
| `NotoSerifJP-Regular.ttf` | Noto Serif JP Regular static embedding face | instantiated from `NotoSerifJP[wght].ttf` at `wght=400` with FontTools 4.62.0 | Google Fonts source revision above | `4927c9fe0985d69f98175d4c6d02eaaad767bd1a259006485797c72c1190db4a` |
| `NotoSerifJP-Bold.ttf` | Noto Serif JP Bold static embedding face | instantiated from `NotoSerifJP[wght].ttf` at `wght=700` with FontTools 4.62.0 | Google Fonts source revision above | `75539a134cdaf84ebb1d08628a365f122833a89e490b10091aaf02b109abe807` |
| `NotoSansMono-Regular.ttf` | Noto Sans Mono Regular static embedding face | instantiated from `NotoSansMono[wdth,wght].ttf` at `wght=400`, `wdth=100` with FontTools 4.62.0 | Google Fonts source revision above | `92fac4a548eccceaa51ef01b1b959b1d3abe45a93c11d3496e54a99995bee110` |
| `NotoSansMono-Bold.ttf` | Noto Sans Mono Bold static embedding face | instantiated from `NotoSansMono[wdth,wght].ttf` at `wght=700`, `wdth=100` with FontTools 4.62.0 | Google Fonts source revision above | `97ba2ac30d42c5cbd75841b23f950d9a0d304a0c178a3a4f7e078e6b929b4525` |
| `OFL.txt` | License | [Google Fonts source](https://github.com/google/fonts/blob/main/ofl/notosansjp/OFL.txt) | Noto CJK `523d033d6cb47f4a80c58a35753646f5c3608a78` | `1c05c68c34f9708415aada51f17e1b0092d2cea709bf4a94cd38114f9e73d7d9` |

The font files are licensed under the [SIL Open Font License, Version 1.1](OFL.txt). The local text-replacement evaluator loads `NotoSansJP[wght].ttf`; static faces are reserved for portable output embedding.
