#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Configuration module for import sorter.

This module contains configuration classes and constants used
by the import sorter utility.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Set, Optional, Pattern
import re
import os


from ..modules.stdlib import _SET_OF_STDLIBS


class ImportType(Enum):
    """
    Enum representing different types of import statements.

    Attributes
    ----------
    FUTURE : int
        Imports from __future__ module.
    STANDARD : int
        Imports from Python standard library.
    THIRD_PARTY : int
        Imports from third-party packages.
    FIRST_PARTY : int
        Imports from the current project.
    LOCAL : int
        Local imports (relative imports).
    """

    FUTURE = 1
    STANDARD = 2
    THIRD_PARTY = 3
    FIRST_PARTY = 4
    LOCAL = 5


@dataclass
class ImportConfig:
    """
    Configuration for import sorting behavior.

    Parameters
    ----------
    line_length : int, optional
        Maximum line length for imports (default: 79).
    multi_line_output : int, optional
        Style for multi-line imports (0-6) (default: 3).
    include_trailing_comma : bool, optional
        Include trailing comma in multi-line imports (default: False).
    force_grid_wrap : int, optional
        Force grid wrap for imports with N items (default: 0).
    use_parentheses : bool, optional
        Use parentheses for multi-line imports (default: True).
    ensure_newline_before_comments : bool, optional
        Ensure newline before inline comments (default: True).
    sections : List[str], optional
        Order of import sections (default: standard order).
    known_standard_library : Set[str], optional
        Known standard library modules.
    known_third_party : Set[str], optional
        Known third-party packages.
    known_first_party : Set[str], optional
        Known first-party modules.
    default_section_order : List[ImportType], optional
        Default order of import sections.
    """

    line_length: int = 79
    multi_line_output: int = 3  # 0: inline, 1-6: various multi-line styles
    include_trailing_comma: bool = False
    force_grid_wrap: int = 0
    use_parentheses: bool = True
    ensure_newline_before_comments: bool = True
    sections: List[str] = field(
        default_factory=lambda: [
            "FUTURE",
            "STANDARD",
            "THIRD_PARTY",
            "FIRST_PARTY",
            "LOCAL",
        ]
    )
    known_standard_library: Set[str] = field(default_factory=set)
    known_third_party: Set[str] = field(default_factory=set)
    known_first_party: Set[str] = field(default_factory=set)

    def __post_init__(self):
        """Initialize known libraries after dataclass creation."""
        if not self.known_standard_library:
            self.known_standard_library = _SET_OF_STDLIBS

    def get_section_order(self) -> List[ImportType]:
        """
        Get import section order based on configuration.

        Returns
        -------
        List[ImportType]
            Ordered list of import sections.
        """
        order_map = {
            "FUTURE": ImportType.FUTURE,
            "STANDARD": ImportType.STANDARD,
            "THIRD_PARTY": ImportType.THIRD_PARTY,
            "FIRST_PARTY": ImportType.FIRST_PARTY,
            "LOCAL": ImportType.LOCAL,
        }

        return [order_map[section] for section in self.sections if section in order_map]

    def load_from_file(self, config_file: str = "pyproject.toml") -> bool:
        """
        Load configuration from a configuration file.

        Parameters
        ----------
        config_file : str, optional
            Path to configuration file (default: "pyproject.toml").

        Returns
        -------
        bool
            True if configuration was loaded successfully, False otherwise.
        """
        try:
            if not os.path.exists(config_file):
                return False

            if config_file.endswith(".toml"):
                import tomli

                with open(config_file, "rb") as f:
                    config = tomli.load(f)

                tool_config = config.get("tool", {}).get("import_sorter", {})
                for key, value in tool_config.items():
                    if hasattr(self, key):
                        setattr(self, key, value)

            elif config_file.endswith(".cfg") or config_file.endswith(".ini"):
                import configparser

                parser = configparser.ConfigParser()
                parser.read(config_file)

                if "import_sorter" in parser:
                    section = parser["import_sorter"]
                    for key, value in section.items():
                        if hasattr(self, key):
                            # Convert string values to appropriate types
                            if key in [
                                "line_length",
                                "multi_line_output",
                                "force_grid_wrap",
                            ]:
                                setattr(self, key, int(value))
                            elif key in [
                                "include_trailing_comma",
                                "use_parentheses",
                                "ensure_newline_before_comments",
                            ]:
                                setattr(
                                    self, key, value.lower() in ["true", "yes", "1"]
                                )
                            elif key == "sections":
                                setattr(
                                    self, key, [s.strip() for s in value.split(",")]
                                )
                            elif key in [
                                "known_standard_library",
                                "known_third_party",
                                "known_first_party",
                            ]:
                                setattr(
                                    self,
                                    key,
                                    set([s.strip() for s in value.split(",")]),
                                )

            return True

        except (ImportError, OSError, ValueError, KeyError):
            return False


DEFAULT_CONFIG = ImportConfig()
