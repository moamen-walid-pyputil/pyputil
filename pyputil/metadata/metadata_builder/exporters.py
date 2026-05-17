#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Exporters for various metadata formats.

Provides functions to export module metadata to different file formats.
"""

import json
import csv
import xml.etree.ElementTree as ET
from xml.dom import minidom
from typing import Dict, Any, List, Optional
from pathlib import Path
import sys

from .types import ModuleMetadata, ExportFormat


class MetadataExporter:
    """Exports module metadata to various formats.

    This class provides methods to convert module metadata dictionaries
    to different file formats including JSON, TOML, YAML, XML, CSV,
    Markdown, plain text, and HTML.

    Attributes
    ----------
    metadata : ModuleMetadata
        Metadata to export
    indent : int
        Indentation level for structured formats

    Examples
    --------
    >>> exporter = MetadataExporter(metadata)
    >>> exporter.export('metadata.json', 'json')
    """

    def __init__(self, metadata: ModuleMetadata, indent: int = 2):
        """
        Initialize metadata exporter.

        Parameters
        ----------
        metadata : ModuleMetadata
            Metadata to export
        indent : int, optional
            Indentation level (default=2)
        """
        self.metadata = metadata
        self.indent = indent

    def export(self, filepath: str, format: ExportFormat = "json"):
        """Export metadata to file.

        Parameters
        ----------
        filepath : str
            Path to output file
        format : ExportFormat, optional
            Output format (default='json')

        Raises
        ------
        ValueError
            If format is not supported
        IOError
            If file cannot be written

        Examples
        --------
        >>> exporter.export('metadata.json', 'json')
        >>> exporter.export('metadata.md', 'md')
        """
        format = format.lower()

        if format == "json":
            self._export_json(filepath)
        elif format == "toml":
            self._export_toml(filepath)
        elif format == "yaml":
            self._export_yaml(filepath)
        elif format == "xml":
            self._export_xml(filepath)
        elif format == "csv":
            self._export_csv(filepath)
        elif format == "md":
            self._export_markdown(filepath)
        elif format == "txt":
            self._export_text(filepath)
        elif format == "html":
            self._export_html(filepath)
        else:
            raise ValueError(f"Unsupported format: {format}")

    def _export_json(self, filepath: str):
        """Export to JSON format.

        Parameters
        ----------
        filepath : str
            Output file path
        """
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, indent=self.indent, ensure_ascii=False)

    def _export_toml(self, filepath: str):
        """Export to TOML format.

        Parameters
        ----------
        filepath : str
            Output file path

        Notes
        -----
        Requires 'toml' package for Python <3.11.
        Uses tomllib for Python >=3.11.
        """
        try:
            # Try tomllib first (Python 3.11+)
            import tomllib
            import tomli_w  # For writing

            with open(filepath, "wb") as f:
                tomli_w.dump(self.metadata, f)
        except ImportError:
            # Fall back to toml package
            try:
                import toml

                with open(filepath, "w", encoding="utf-8") as f:
                    toml.dump(self.metadata, f)
            except ImportError:
                raise ImportError(
                    "TOML export requires 'toml' package. "
                    "Install with: pip install toml"
                )

    def _export_yaml(self, filepath: str):
        """Export to YAML format.

        Parameters
        ----------
        filepath : str
            Output file path

        Notes
        -----
        Requires 'pyyaml' package.
        """
        try:
            import yaml

            with open(filepath, "w", encoding="utf-8") as f:
                yaml.dump(
                    self.metadata, f, default_flow_style=False, allow_unicode=True
                )
        except ImportError:
            raise ImportError(
                "YAML export requires 'pyyaml' package. "
                "Install with: pip install pyyaml"
            )

    def _export_xml(self, filepath: str):
        """Export to XML format.

        Parameters
        ----------
        filepath : str
            Output file path
        """

        def dict_to_xml(tag: str, d: Dict[str, Any]) -> ET.Element:
            """Convert dictionary to XML element."""
            elem = ET.Element(tag)

            for key, val in d.items():
                if isinstance(val, dict):
                    elem.append(dict_to_xml(key, val))
                elif isinstance(val, list):
                    list_elem = ET.Element(key)
                    for item in val:
                        if isinstance(item, dict):
                            list_elem.append(dict_to_xml("item", item))
                        else:
                            item_elem = ET.Element("item")
                            item_elem.text = str(item)
                            list_elem.append(item_elem)
                    elem.append(list_elem)
                else:
                    child = ET.Element(key)
                    child.text = str(val)
                    elem.append(child)

            return elem

        root = dict_to_xml("metadata", self.metadata)

        # Pretty print XML
        xml_str = ET.tostring(root, encoding="unicode")
        dom = minidom.parseString(xml_str)
        pretty_xml = dom.toprettyxml(indent="  ")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(pretty_xml)

    def _export_csv(self, filepath: str):
        """Export to CSV format.

        Parameters
        ----------
        filepath : str
            Output file path

        Notes
        -----
        CSV format is flattened for key-value pairs.
        Lists are converted to comma-separated strings.
        """

        def flatten_dict(d: Dict[str, Any], prefix: str = "") -> Dict[str, str]:
            """Flatten nested dictionary."""
            items = {}
            for k, v in d.items():
                key = f"{prefix}.{k}" if prefix else k

                if isinstance(v, dict):
                    items.update(flatten_dict(v, key))
                elif isinstance(v, list):
                    items[key] = ", ".join(str(item) for item in v)
                else:
                    items[key] = str(v) if v is not None else ""

            return items

        flat_data = flatten_dict(self.metadata)

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Key", "Value"])
            for key, value in flat_data.items():
                writer.writerow([key, value])

    def _export_markdown(self, filepath: str):
        """Export to Markdown format.

        Parameters
        ----------
        filepath : str
            Output file path
        """
        lines = [
            f"# Module Metadata: {self.metadata['identity']['name']}",
            "",
            f"**Analysis Time**: {self.metadata['meta_timestamp']}",
            f"**Python Version**: {self.metadata['python_version']}",
            "",
            "## Identity",
            f"- **Name**: {self.metadata['identity']['name']}",
            f"- **ID**: {self.metadata['identity']['id']}",
            f"- **Full Name**: {self.metadata['identity']['full_name'] or 'N/A'}",
            "",
            "## Location",
            f"- **File**: {self.metadata['location']['file'] or 'Built-in'}",
            f"- **Origin**: {self.metadata['location']['origin'] or 'N/A'}",
            f"- **Package**: {self.metadata['location']['package'] or 'N/A'}",
            "",
            "## Structure",
            f"- **Total Attributes**: {self.metadata['structure']['attributes_count']}",
            f"- **Classes**: {len(self.metadata['structure']['classes'])}",
            f"- **Functions**: {len(self.metadata['structure']['functions'])}",
            f"- **Variables**: {len(self.metadata['structure']['variables'])}",
            f"- **Submodules**: {len(self.metadata['structure']['submodules'])}",
            "",
            "## Documentation",
            f"- **Has Documentation**: {self.metadata['documentation']['has_doc']}",
            f"- **Doc Length**: {self.metadata['documentation']['doc_length']} chars",
            "",
            "## Risk Assessment",
            f"- **Risk Level**: {self.metadata['risk_flags']['risk_level'].upper()}",
            f"- **Contains exec**: {self.metadata['risk_flags']['exec']}",
            f"- **Contains eval**: {self.metadata['risk_flags']['eval']}",
            "",
            "## Classes",
        ]

        for cls in self.metadata["structure"]["classes"][:10]:  # Show first 10
            lines.append(f"- {cls}")
        if len(self.metadata["structure"]["classes"]) > 10:
            lines.append(
                f"- ... and {len(self.metadata['structure']['classes']) - 10} more"
            )

        lines.append("")
        lines.append("## Functions")
        for func in self.metadata["structure"]["functions"][:10]:
            lines.append(f"- {func}")
        if len(self.metadata["structure"]["functions"]) > 10:
            lines.append(
                f"- ... and {len(self.metadata['structure']['functions']) - 10} more"
            )

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _export_text(self, filepath: str):
        """Export to plain text format.

        Parameters
        ----------
        filepath : str
            Output file path
        """

        def dict_to_text(d: Dict[str, Any], indent: int = 0) -> List[str]:
            """Convert dictionary to text lines."""
            lines = []
            prefix = " " * indent

            for key, value in d.items():
                if isinstance(value, dict):
                    lines.append(f"{prefix}{key}:")
                    lines.extend(dict_to_text(value, indent + 2))
                elif isinstance(value, list):
                    lines.append(f"{prefix}{key}:")
                    for item in value:
                        lines.append(f"{prefix}  - {item}")
                else:
                    lines.append(f"{prefix}{key}: {value}")

            return lines

        lines = [f"Module Metadata: {self.metadata['identity']['name']}", "=" * 50, ""]
        lines.extend(dict_to_text(self.metadata))

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _export_html(self, filepath: str):
        """Export to HTML format.

        Parameters
        ----------
        filepath : str
            Output file path
        """
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Module Metadata: {self.metadata['identity']['name']}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; line-height: 1.6; }}
        h1, h2 {{ color: #333; }}
        .section {{ margin-bottom: 30px; padding: 15px; border: 1px solid #ddd; border-radius: 5px; }}
        .risk-high {{ background-color: #ffcccc; }}
        .risk-medium {{ background-color: #fff3cd; }}
        .risk-low {{ background-color: #d4edda; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
        .mono {{ font-family: monospace; }}
    </style>
</head>
<body>
    <h1>Module Metadata: {self.metadata['identity']['name']}</h1>
    
    <div class="section">
        <h2>Overview</h2>
        <p><strong>Analysis Time:</strong> {self.metadata['meta_timestamp']}</p>
        <p><strong>Python Version:</strong> {self.metadata['python_version']}</p>
    </div>
    
    <div class="section">
        <h2>Identity</h2>
        <table>
            <tr><th>Property</th><th>Value</th></tr>
            <tr><td>Name</td><td>{self.metadata['identity']['name']}</td></tr>
            <tr><td>ID</td><td>{self.metadata['identity']['id']}</td></tr>
            <tr><td>Full Name</td><td>{self.metadata['identity']['full_name'] or 'N/A'}</td></tr>
        </table>
    </div>
    
    <div class="section risk-{self.metadata['risk_flags']['risk_level']}">
        <h2>Risk Assessment</h2>
        <p><strong>Risk Level:</strong> {self.metadata['risk_flags']['risk_level'].upper()}</p>
        <p><strong>Contains exec:</strong> {self.metadata['risk_flags']['exec']}</p>
        <p><strong>Contains eval:</strong> {self.metadata['risk_flags']['eval']}</p>
    </div>
    
    <div class="section">
        <h2>Structure Summary</h2>
        <table>
            <tr><th>Type</th><th>Count</th></tr>
            <tr><td>Total Attributes</td><td>{self.metadata['structure']['attributes_count']}</td></tr>
            <tr><td>Classes</td><td>{len(self.metadata['structure']['classes'])}</td></tr>
            <tr><td>Functions</td><td>{len(self.metadata['structure']['functions'])}</td></tr>
            <tr><td>Variables</td><td>{len(self.metadata['structure']['variables'])}</td></tr>
        </table>
    </div>
    
    <div class="section">
        <h2>Documentation</h2>
        <p><strong>Has Documentation:</strong> {self.metadata['documentation']['has_doc']}</p>
        <div class="mono" style="background: #f8f9fa; padding: 10px; border-radius: 3px;">
            {self.metadata['documentation']['docstring'] or 'No documentation available'}
        </div>
    </div>
</body>
</html>"""

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)


def export_metadata(
    metadata: ModuleMetadata,
    filepath: str,
    format: ExportFormat = "json",
    indent: int = 2,
):
    """Convenience function to export metadata.

    Parameters
    ----------
    metadata : ModuleMetadata
        Metadata to export
    filepath : str
        Output file path
    format : ExportFormat, optional
        Output format (default='json')
    indent : int, optional
        Indentation level (default=2)

    Examples
    --------
    >>> export_metadata(metadata, 'output.json', 'json')
    >>> export_metadata(metadata, 'report.md', 'md')
    """
    exporter = MetadataExporter(metadata, indent)
    exporter.export(filepath, format)
