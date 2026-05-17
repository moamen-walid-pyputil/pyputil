#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Configuration management for metadata analyzer.

Provides configuration loading, saving, and validation.
"""

import json
import os
from typing import Dict, Any, Optional, List
from pathlib import Path
from dataclasses import dataclass, asdict, field
from enum import Enum

from .types import AnalysisLevel, ExportFormat


class LogLevel(Enum):
    """Logging level enumeration."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class AnalyzerConfig:
    """Configuration for metadata analyzer.

    Attributes
    ----------
    include_private : bool
        Include private attributes in analysis
    analysis_level : AnalysisLevel
        Depth of analysis
    default_format : ExportFormat
        Default export format
    indent_size : int
        Indentation for structured formats
    log_level : LogLevel
        Logging level
    max_attributes_display : int
        Maximum attributes to display in summaries
    timeout_seconds : float
        Analysis timeout in seconds
    cache_results : bool
        Cache analysis results
    output_directory : str
        Default output directory
    """

    include_private: bool = False
    analysis_level: AnalysisLevel = "standard"
    default_format: ExportFormat = "json"
    indent_size: int = 2
    log_level: LogLevel = LogLevel.INFO
    max_attributes_display: int = 20
    timeout_seconds: float = 30.0
    cache_results: bool = True
    output_directory: str = "./metadata_reports"

    # Export-specific settings
    export_settings: Dict[str, Any] = field(
        default_factory=lambda: {
            "json": {"ensure_ascii": False},
            "yaml": {"default_flow_style": False},
            "html": {"template": "default"},
        }
    )

    # Module-specific overrides
    module_overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)


class ConfigManager:
    """Manages analyzer configuration.

    This class handles loading, saving, and validating configuration
    for the metadata analyzer.

    Attributes
    ----------
    config : AnalyzerConfig
        Current configuration
    config_file : Optional[Path]
        Path to configuration file

    Examples
    --------
    >>> manager = ConfigManager()
    >>> config = manager.load_default()
    >>> config.analysis_level = 'detailed'
    >>> manager.save('config.json')
    """

    DEFAULT_CONFIG_FILE = "metadata_analyzer_config.json"

    def __init__(self, config_file: Optional[str] = None):
        """
        Initialize configuration manager.

        Parameters
        ----------
        config_file : Optional[str], optional
            Path to configuration file
        """
        self.config_file = Path(config_file) if config_file else None
        self.config = self.load_default()

        if config_file and os.path.exists(config_file):
            self.load(config_file)

    def load_default(self) -> AnalyzerConfig:
        """Load default configuration.

        Returns
        -------
        AnalyzerConfig
            Default configuration
        """
        return AnalyzerConfig()

    def load(self, filepath: str) -> AnalyzerConfig:
        """Load configuration from file.

        Parameters
        ----------
        filepath : str
            Path to configuration file

        Returns
        -------
        AnalyzerConfig
            Loaded configuration

        Raises
        ------
        FileNotFoundError
            If configuration file doesn't exist
        ValueError
            If configuration is invalid
        """
        filepath = Path(filepath)

        if not filepath.exists():
            raise FileNotFoundError(f"Configuration file not found: {filepath}")

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Convert string enums back to Enum values
        if "analysis_level" in data:
            data["analysis_level"] = data["analysis_level"]

        if "default_format" in data:
            data["default_format"] = data["default_format"]

        if "log_level" in data:
            data["log_level"] = LogLevel(data["log_level"])

        # Create config object
        self.config = AnalyzerConfig(**data)
        self.config_file = filepath

        return self.config

    def save(self, filepath: Optional[str] = None) -> str:
        """Save configuration to file.

        Parameters
        ----------
        filepath : Optional[str], optional
            Path to save configuration, uses current if None

        Returns
        -------
        str
            Path where configuration was saved
        """
        if filepath:
            save_path = Path(filepath)
        elif self.config_file:
            save_path = self.config_file
        else:
            save_path = Path(self.DEFAULT_CONFIG_FILE)

        # Ensure directory exists
        save_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert to dict
        data = asdict(self.config)

        # Convert Enum values to strings
        data["analysis_level"] = self.config.analysis_level
        data["default_format"] = self.config.default_format
        data["log_level"] = self.config.log_level.value

        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        self.config_file = save_path
        return str(save_path)

    def update(self, **kwargs) -> None:
        """Update configuration with new values.

        Parameters
        ----------
        **kwargs
            Configuration parameters to update

        Examples
        --------
        >>> manager.update(analysis_level='detailed', include_private=True)
        """
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
            else:
                raise AttributeError(f"Invalid configuration parameter: {key}")

    def get_module_override(self, module_name: str) -> Dict[str, Any]:
        """Get module-specific configuration overrides.

        Parameters
        ----------
        module_name : str
            Module name

        Returns
        -------
        Dict[str, Any]
            Module-specific settings

        Examples
        --------
        >>> overrides = manager.get_module_override('os')
        >>> overrides.get('analysis_level', 'standard')
        """
        return self.config.module_overrides.get(module_name, {})

    def set_module_override(self, module_name: str, settings: Dict[str, Any]) -> None:
        """Set module-specific configuration overrides.

        Parameters
        ----------
        module_name : str
            Module name
        settings : Dict[str, Any]
            Module-specific settings
        """
        self.config.module_overrides[module_name] = settings

    def validate(self) -> List[str]:
        """Validate current configuration.

        Returns
        -------
        List[str]
            List of validation errors, empty if valid
        """
        errors = []

        # Validate analysis level
        if self.config.analysis_level not in ("basic", "standard", "detailed", "full"):
            errors.append(f"Invalid analysis level: {self.config.analysis_level}")

        # Validate indent size
        if self.config.indent_size < 0 or self.config.indent_size > 8:
            errors.append(f"Invalid indent size: {self.config.indent_size}")

        # Validate timeout
        if self.config.timeout_seconds <= 0:
            errors.append(f"Invalid timeout: {self.config.timeout_seconds}")

        # Validate output directory
        try:
            Path(self.config.output_directory)
        except Exception as e:
            errors.append(f"Invalid output directory: {e}")

        return errors
