"""Process supported bitmap and document files for visible-text replacement."""

from pipeline.folder_replacement.processor import FolderReplacementResult, replace_input_folder
from pipeline.folder_replacement.filters import parse_include_patterns

__all__ = ["FolderReplacementResult", "parse_include_patterns", "replace_input_folder"]
