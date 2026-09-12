# Project background

## Why this exists

This project began as an exploration of the difficult middle part of document
translation: replacing what people can see without treating every document as
plain text or flattening it into an image.

Text substitution in document structures is well understood, and OCR plus
translation are established problems. The more interesting gap is making the
replacement still belong in the document: it should remain readable, fit a
reasonable visual area, and handle text that appears in embedded bitmaps as
well as editable document objects.

| Area | Solved? | My target |
|---|---:|---|
| Replacing text in documents | ✅ | Easy — lots of people do this |
| OCR and translation | ✅ | Hard — lots of people solved this |
| Presentation-aware text replacement | 🎯 | Medium — ensure replacements scale nicely, either as rich-text objects or rendered bitmaps |
| Nested bitmaps in rich-text documents | 🎯 | Medium |

The project is not intended to claim that every document can be translated
losslessly. Its approach is to preserve native structures where a safe route
exists, use OCR only for visible image content, and retain content that cannot
be handled reliably. The [format-support guide](folder-replacer-format-support.md)
describes those boundaries in detail.
