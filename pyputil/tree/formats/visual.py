#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Visual output formatters for dependency trees supporting multiple visualization formats.

This module provides robust visualization capabilities for dependency trees,
supporting Graphviz DOT, Mermaid, and interactive HTML formats with advanced
styling, and comprehensive error handling.

Key Features
------------
- **Graphviz DOT**: Professional static graph visualization with customizable styling
- **Mermaid**: Interactive web-based diagrams compatible with markdown and documentation
- **HTML/CSS/JS**: Full-featured interactive web visualization with search and filtering
- **Multi-format Export**: Generate multiple formats from a single tree structure
- **Extensive Styling**: Customizable colors, shapes, and themes for all formats
- **Robust Error Handling**: Comprehensive validation and informative error messages
- **Unicode Support**: Full support for international characters and special symbols

Architecture Notes
-----------------
The module uses a dictionary-based tree structure throughout. All functions
expect and return standard Python dictionaries, NEVER dataclass instances.
This ensures maximum compatibility and avoids serialization issues.

Dependency Tree Structure
------------------------
The standard tree structure is a nested dictionary:
{
    "name": str,           # Package name (required)
    "version": str,        # Version string (optional)
    "status": str,         # 'installed', 'not_installed', 'error', 'cycle_detected'
    "license": str,        # License identifier (optional)
    "homepage": str,       # Project URL (optional)
    "description": str,    # Short description (optional)
    "dependencies": [      # List of dependency dictionaries (optional)
        {...},             # Recursive tree structure
    ]
}

Usage Patterns
-------------
1. Basic HTML Export:
   >>> tree = {'name': 'myapp', 'dependencies': [...]}
   >>> html = export_to_html(tree, output_file='deps.html')

2. Graphviz with Styling:
   >>> style = NodeStyle(installed_fill="#e8f5e9")
   >>> dot = export_to_graphviz(tree, node_style=style)

3. Multi-format Export:
   >>> files = export_to_multiple_formats(tree, 'output', 
   ...                                    formats=['html', 'graphviz'])

Warning
-------
This module GENERATES JavaScript code embedded in Python strings.
When modifying the JavaScript portions, be EXTREMELY careful with:
- Template literals: Use proper escaping
- String concatenation: Use + operator in JS
- Variable access: Always use bracket notation in generated JS
"""

import json
import warnings
from typing import Dict, Optional, List, Any, Union, Tuple
from pathlib import Path
from datetime import datetime
import re
import sys


class VisualizationError(Exception):
    """
    Exception raised for errors in visualization operations.
    
    This custom exception provides detailed error information including
    the format that caused the error and the original exception if any.
    
    Attributes
    ----------
    message : str
        Human-readable description of the error
    format_name : str, optional
        The visualization format that caused the error
    original_error : Exception, optional
        Original exception that caused this error
    
    Examples
    --------
    >>> raise VisualizationError("Failed to generate Graphviz output", 
    ...                          format_name="graphviz")
    >>> raise VisualizationError("Invalid tree structure", 
    ...                          format_name="html",
    ...                          original_error=ValueError("Missing name"))
    """
    
    def __init__(self, message: str, format_name: Optional[str] = None,
                 original_error: Optional[Exception] = None):
        """
        Initialize VisualizationError with detailed context.
        
        Parameters
        ----------
        message : str
            Human-readable error description
        format_name : str, optional
            The visualization format that caused the error
        original_error : Exception, optional
            Original exception that caused this error
        """
        self.message = message
        self.format_name = format_name
        self.original_error = original_error
        super().__init__(self._format_message())
    
    def _format_message(self) -> str:
        """
        Format the error message with format information.
        
        Returns
        -------
        str
            Formatted error message with format context
        """
        if self.format_name:
            return f"Visualization error ({self.format_name}): {self.message}"
        return f"Visualization error: {self.message}"


class NodeStyle:
    """
    Styling configuration for visualization nodes in all output formats.
    
    This class centralizes node styling across all visualization formats,
    providing consistent color schemes and shape configurations. Each status
    type gets a distinct visual treatment to make dependency status immediately
    recognizable.
    
    Color Scheme Logic
    -----------------
    - **installed**: Default white/transparent (neutral, normal state)
    - **not_installed**: Light gray (subtle, indicating absence)
    - **error**: Light red (attention-grabbing, needs immediate action)
    - **cycle_detected**: Light yellow (warning, potential issues)
    
    Parameters
    ----------
    default_fill : str, default="#ffffff"
        Default fill color for nodes (hex color code)
    default_stroke : str, default="#333333"
        Default stroke/border color for nodes
    default_shape : str, default="box"
        Default node shape for Graphviz (box, ellipse, circle, etc.)
    installed_fill : str, default="#ffffff"
        Fill color for successfully installed packages
    not_installed_fill : str, default="#f0f0f0"
        Fill color for packages that are not installed
    error_fill : str, default="#ffcccc"
        Fill color for packages with installation errors
    cycle_fill : str, default="#ffffcc"
        Fill color for packages involved in dependency cycles
    font_color : str, default="#000000"
        Default font color for node labels
    font_size : int, default=12
        Font size in points for node labels
    
    Examples
    --------
    >>> # Default styling
    >>> default_style = NodeStyle()
    
    >>> # Custom dark theme styling
    >>> dark_style = NodeStyle(
    ...     default_fill="#2d2d2d",
    ...     default_stroke="#667eea",
    ...     installed_fill="#1a472a",
    ...     error_fill="#4a1a1a",
    ...     font_color="#ffffff",
    ...     font_size=14
    ... )
    
    >>> # Light theme with green accents
    >>> light_style = NodeStyle(
    ...     installed_fill="#e8f5e9",
    ...     not_installed_fill="#f5f5f5",
    ...     error_fill="#ffebee",
    ...     cycle_fill="#fff8e1"
    ... )
    """
    
    def __init__(self, default_fill: str = "#ffffff",
                 default_stroke: str = "#333333",
                 default_shape: str = "box",
                 installed_fill: str = "#ffffff",
                 not_installed_fill: str = "#f0f0f0",
                 error_fill: str = "#ffcccc",
                 cycle_fill: str = "#ffffcc",
                 font_color: str = "#000000",
                 font_size: int = 12):
        
        # Store all styling properties
        self.default_fill = default_fill
        self.default_stroke = default_stroke
        self.default_shape = default_shape
        self.installed_fill = installed_fill
        self.not_installed_fill = not_installed_fill
        self.error_fill = error_fill
        self.cycle_fill = cycle_fill
        self.font_color = font_color
        self.font_size = font_size
        
        # Build lookup table for fast status-to-color mapping
        self._status_styles = {
            "installed": installed_fill,
            "not_installed": not_installed_fill,
            "error": error_fill,
            "cycle_detected": cycle_fill
        }
    
    def get_fill_color(self, status: str) -> str:
        """
        Get fill color based on node installation status.
        
        Parameters
        ----------
        status : str
            Node status identifier ('installed', 'not_installed', 
            'error', 'cycle_detected')
        
        Returns
        -------
        str
            Hexadecimal color code for the given status
        
        Examples
        --------
        >>> style = NodeStyle()
        >>> style.get_fill_color("error")
        '#ffcccc'
        >>> style.get_fill_color("installed")
        '#ffffff'
        >>> style.get_fill_color("unknown_status")  # Falls back to default
        '#ffffff'
        """
        return self._status_styles.get(status, self.default_fill)
    
    def get_graphviz_style(self, status: str) -> str:
        """
        Generate complete Graphviz DOT style attribute string for a node.
        
        Creates a string suitable for use in Graphviz node definitions
        with proper fill color and shape based on installation status.
        
        Parameters
        ----------
        status : str
            Node installation status
        
        Returns
        -------
        str
            Graphviz style attribute string like:
            'style="filled", fillcolor="#ffcccc", shape="box"'
        
        Examples
        --------
        >>> style = NodeStyle()
        >>> style.get_graphviz_style("error")
        'style="filled", fillcolor="#ffcccc", shape="box"'
        """
        fill_color = self.get_fill_color(status)
        return f'style="filled", fillcolor="{fill_color}", shape="{self.default_shape}"'
    
    def get_mermaid_class(self, status: str) -> str:
        """
        Generate Mermaid CSS class modifier for a node.
        
        Mermaid uses :::className syntax for applying CSS classes to nodes.
        This method returns the appropriate class modifier based on status.
        
        Parameters
        ----------
        status : str
            Node installation status
        
        Returns
        -------
        str
            Mermaid class modifier or empty string for default styling
        
        Examples
        --------
        >>> style = NodeStyle()
        >>> style.get_mermaid_class("not_installed")
        ':::not_installed'
        >>> style.get_mermaid_class("installed")
        ''
        """
        if status == "not_installed":
            return ":::not_installed"
        elif status == "error":
            return ":::error"
        elif status == "cycle_detected":
            return ":::cycle"
        return ""


def _sanitize_label(text: str, format_type: str = "graphviz") -> str:
    """
    Sanitize text labels for safe embedding in different output formats.
    
    Each format has different escaping requirements. This function handles
    all the necessary transformations to ensure safe output.
    
    Format-specific escaping rules
    -----------------------------
    - **graphviz**: Escape backslashes, quotes, remove control characters
    - **mermaid**: Replace newlines, escape quotes with HTML entities
    - **html**: Escape all HTML special characters (<, >, &, ", ')
    
    Parameters
    ----------
    text : str
        Raw text to sanitize
    format_type : str
        Target format: 'graphviz', 'mermaid', or 'html'
    
    Returns
    -------
    str
        Sanitized text safe for the specified format
    
    Examples
    --------
    >>> _sanitize_label('Hello "world"', 'graphviz')
    'Hello \\"world\\"'
    >>> _sanitize_label('Package<1.0>', 'html')
    'Package&lt;1.0&gt;'
    >>> _sanitize_label('Line1\\nLine2', 'mermaid')
    'Line1 Line2'
    
    Notes
    -----
    Always sanitize user-provided or package-generated strings before
    embedding them in generated code to prevent injection attacks and
    formatting errors.
    """
    # Handle None or non-string inputs gracefully
    if not isinstance(text, str):
        return str(text)
    
    if format_type == "graphviz":
        # Graphviz escaping: backslashes first, then quotes
        text = text.replace('\\', '\\\\')
        text = text.replace('"', '\\"')
        # Remove control characters that break DOT format
        text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
        return text
    
    elif format_type == "mermaid":
        # Mermaid doesn't support newlines in node labels
        text = text.replace('\n', ' ').replace('\r', '')
        # Use HTML entity for quotes in Mermaid
        text = text.replace('"', '&quot;')
        return text
    
    elif format_type == "html":
        # Standard HTML entity escaping
        html_escape_table = {
            "&": "&amp;",
            '"': "&quot;",
            "'": "&apos;",
            ">": "&gt;",
            "<": "&lt;",
        }
        return "".join(html_escape_table.get(c, c) for c in text)
    
    # Unknown format: return as-is with basic cleaning
    return text.strip()


def _validate_tree(tree: Dict, format_name: str) -> None:
    """
    Validate dependency tree structure before attempting visualization.
    
    Performs structural validation to catch common issues early:
    - Tree must be a dictionary (not list, string, or dataclass)
    - Tree must have a 'name' field (absolute minimum requirement)
    - Tree should not be empty or malformed
    
    Parameters
    ----------
    tree : Dict
        Dependency tree to validate
    format_name : str
        Name of the visualization format (for error messages)
    
    Raises
    ------
    VisualizationError
        If tree structure is invalid with descriptive message
    
    Examples
    --------
    >>> valid_tree = {'name': 'mypackage', 'version': '1.0', 'dependencies': []}
    >>> _validate_tree(valid_tree, 'html')  # No error raised
    
    >>> _validate_tree([], 'html')  # Will raise VisualizationError
    >>> _validate_tree({'version': '1.0'}, 'html')  # Will raise VisualizationError
    """
    # Check that tree is a dictionary (NOT a dataclass or other type)
    if not isinstance(tree, dict):
        raise VisualizationError(
            f"Tree must be a dictionary, got {type(tree).__name__}. "
            "Ensure you are passing a dict, not a dataclass or other object.",
            format_name=format_name
        )
    
    # Check for required 'name' field
    if 'name' not in tree:
        raise VisualizationError(
            "Tree missing required 'name' field. "
            "Each node must have at least {'name': 'package_name'}.",
            format_name=format_name
        )
    
    # Validate name is a string
    if not isinstance(tree.get('name'), str):
        raise VisualizationError(
            f"Tree 'name' must be a string, got {type(tree['name']).__name__}",
            format_name=format_name
        )


def _collect_dependencies(node: Dict) -> List[Dict]:
    """
    Collect all dependencies from a node, handling multiple dependency formats.
    
    Supports both simple and complex dependency structures:
    1. Simple: {'dependencies': [{...}, {...}]}
    2. By type: {'dependencies_by_type': {'runtime': [...], 'dev': [...]}}
    3. Combined: Both 'dependencies' and 'dependencies_by_type' present
    
    IMPORTANT: This function treats nodes as DICTIONARIES, not dataclasses.
    All access is through dict methods (.get(), ['key'], isinstance checks).
    
    Parameters
    ----------
    node : Dict
        Node dictionary from dependency tree (NOT a dataclass)
    
    Returns
    -------
    List[Dict]
        Flat list of all dependency dictionaries found
    
    Examples
    --------
    >>> node = {
    ...     'name': 'package',
    ...     'dependencies': [
    ...         {'name': 'dep1', 'version': '1.0'},
    ...     ],
    ...     'dependencies_by_type': {
    ...         'dev': [{'name': 'dep2', 'version': '2.0'}]
    ...     }
    ... }
    >>> deps = _collect_dependencies(node)
    >>> len(deps)
    2
    """
    dependencies = []
    
    # Collect standard dependencies list
    if "dependencies" in node and isinstance(node["dependencies"], list):
        dependencies.extend(node["dependencies"])
    
    # Collect categorized dependencies
    if "dependencies_by_type" in node and isinstance(node["dependencies_by_type"], dict):
        for deps_list in node["dependencies_by_type"].values():
            if isinstance(deps_list, list):
                dependencies.extend(deps_list)
    
    return dependencies


def export_to_graphviz(tree: Dict, output_file: Optional[str] = None,
                      rankdir: str = "LR", node_style: Optional[NodeStyle] = None,
                      show_version: bool = True, show_status: bool = True,
                      ranksep: Optional[float] = None, nodesep: Optional[float] = None,
                      concentrate: bool = True) -> str:
    """
    Export dependency tree to Graphviz DOT format with advanced styling.
    
    Graphviz is a powerful graph visualization tool that produces
    professional-quality static diagrams. This function generates
    DOT language output that can be rendered to PNG, SVG, PDF, etc.
    
    IMPORTANT: This function processes DICTIONARY trees, not dataclasses.
    All node access uses dict methods (node.get('key'), node['key']).
    
    Parameters
    ----------
    tree : dict
        Dependency tree structure as a nested dictionary with fields:
        - 'name' (str, required): Package name
        - 'version' (str, optional): Version string
        - 'status' (str, optional): Installation status
        - 'dependencies' (list, optional): Child dependency dicts
    output_file : str, optional
        Path to save DOT file. If None, returns string only.
    rankdir : str, default="LR"
        Graph layout direction:
        - 'LR': Left to Right (horizontal)
        - 'TB': Top to Bottom (vertical)
        - 'RL': Right to Left
        - 'BT': Bottom to Top
    node_style : NodeStyle, optional
        Custom styling configuration for nodes
    show_version : bool, default=True
        Include package versions in node labels
    show_status : bool, default=True
        Include installation status badges in node labels
    ranksep : float, optional
        Vertical separation between ranks (in inches)
    nodesep : float, optional
        Horizontal separation between nodes (in inches)
    concentrate : bool, default=True
        Merge multiple edges between same nodes for cleaner output
    
    Returns
    -------
    str
        Graphviz DOT language string
    
    Raises
    ------
    VisualizationError
        If tree structure is invalid or file cannot be written
    
    Notes
    -----
    Rendering DOT files requires Graphviz tools:
    ```bash
    # Generate PNG image
    dot -Tpng dependencies.dot -o dependencies.png
    
    # Generate SVG for web
    dot -Tsvg dependencies.dot -o dependencies.svg
    
    # Generate PDF for documentation
    dot -Tpdf dependencies.dot -o dependencies.pdf
    ```
    
    Online renderers available at:
    - https://dreampuf.github.io/GraphvizOnline/
    - https://edotor.net/
    
    Examples
    --------
    >>> # Basic dependency tree
    >>> tree = {
    ...     'name': 'requests',
    ...     'version': '2.28.1',
    ...     'status': 'installed',
    ...     'dependencies': [
    ...         {'name': 'urllib3', 'version': '1.26.13', 'status': 'installed'},
    ...         {'name': 'certifi', 'version': '2022.12.7', 'status': 'installed'}
    ...     ]
    ... }
    
    >>> # Generate DOT output
    >>> dot_string = export_to_graphviz(tree)
    >>> print(dot_string[:80])
    digraph Dependencies {
        rankdir=LR;
    
    >>> # Custom styling and save to file
    >>> style = NodeStyle(installed_fill="#e8f5e9", error_fill="#ffebee")
    >>> dot = export_to_graphviz(tree, output_file='deps.dot', 
    ...                          rankdir='TB', node_style=style)
    
    >>> # Minimal output without version/status
    >>> dot = export_to_graphviz(tree, show_version=False, show_status=False)
    """
    # Validate tree structure (ensures dict type, has name)
    _validate_tree(tree, "graphviz")
    
    # Use default styling if none provided
    if node_style is None:
        node_style = NodeStyle()
    
    # Initialize DOT graph structure
    dot_lines = [
        "digraph Dependencies {",
        f"    rankdir={rankdir};",
        f"    concentrate={'true' if concentrate else 'false'};",
        f"    node [shape={node_style.default_shape}];",
    ]
    
    # Add optional graph attributes for finer layout control
    if ranksep is not None:
        dot_lines.append(f"    ranksep={ranksep};")
    if nodesep is not None:
        dot_lines.append(f"    nodesep={nodesep};")
    
    # Track unique nodes to avoid duplicates (by name|version key)
    node_ids: Dict[str, str] = {}
    node_counter = 0
    
    def add_node(node: Dict, parent_id: Optional[str] = None) -> str:
        """
        Recursively add a node to the Graphviz graph.
        
        Parameters
        ----------
        node : Dict
            Node dictionary (NOT dataclass)
        parent_id : str, optional
            ID of parent node for edge creation
        
        Returns
        -------
        str
            Generated node ID
        """
        nonlocal node_counter
        
        # Skip None nodes gracefully
        if node is None:
            return ""
        
        # Extract node information using dict methods (NOT attribute access)
        node_name = node.get("name", "unknown")
        node_version = node.get("version", "")
        node_status = node.get("status", "installed")
        
        # Create unique key for deduplication
        node_key = f"{node_name}|{node_version}"
        
        # Only create new node if we haven't seen this package+version before
        if node_key not in node_ids:
            node_id = f"node{node_counter}"
            node_counter += 1
            node_ids[node_key] = node_id
            
            # Build node label with optional version and status
            label_parts = [_sanitize_label(node_name, "graphviz")]
            if show_version and node_version:
                label_parts.append(f"\\n{_sanitize_label(node_version, 'graphviz')}")
            if show_status and node_status != "installed":
                status_text = node_status.replace('_', ' ').title()
                label_parts.append(f"\\n[{status_text}]")
            
            label = "".join(label_parts)
            
            # Apply status-based styling
            style_str = node_style.get_graphviz_style(node_status)
            
            # Add node definition to graph
            dot_lines.append(
                f'    {node_id} [label="{label}", {style_str}];'
            )
        else:
            # Reuse existing node ID
            node_id = node_ids[node_key]
        
        # Create edge from parent to this node (avoid self-loops)
        if parent_id is not None and parent_id != node_id:
            dot_lines.append(f"    {parent_id} -> {node_id};")
        
        # Recursively process all dependencies
        dependencies = _collect_dependencies(node)
        for dep in dependencies:
            if isinstance(dep, dict):
                add_node(dep, node_id)
            # Note: Skip non-dict dependencies gracefully
        
        return node_id
    
    # Process the entire tree starting from root
    add_node(tree)
    
    # Close the graph
    dot_lines.append("}")
    
    dot_output = "\n".join(dot_lines)
    
    # Write to file if path provided
    if output_file:
        try:
            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(dot_output)
        except IOError as e:
            raise VisualizationError(
                f"Failed to write DOT file '{output_file}': {e}",
                format_name="graphviz",
                original_error=e
            )
    
    return dot_output


def export_to_mermaid(tree: Dict, output_file: Optional[str] = None,
                     direction: str = "LR", node_style: Optional[NodeStyle] = None,
                     show_version: bool = True, show_status: bool = True,
                     theme: str = "default", add_classes: bool = True) -> str:
    """
    Export dependency tree to Mermaid diagram format for web visualization.
    
    Mermaid is a JavaScript-based diagramming tool that renders flowcharts
    and diagrams in web browsers. It integrates seamlessly with:
    - GitHub/GitLab markdown (auto-renders in README files)
    - Documentation generators (MkDocs, Sphinx)
    - Online editors (https://mermaid.live/)
    
    IMPORTANT: This function processes DICTIONARY trees, not dataclasses.
    All node access uses dict methods (node.get('key'), node['key']).
    
    Parameters
    ----------
    tree : dict
        Dependency tree structure as nested dictionary
    output_file : str, optional
        Path to save .mmd file
    direction : str, default="LR"
        Graph direction:
        - 'LR': Left to right (horizontal)
        - 'TB': Top to bottom (vertical)
        - 'RL': Right to left
        - 'BT': Bottom to top
    node_style : NodeStyle, optional
        Custom node styling
    show_version : bool, default=True
        Include version numbers in node labels
    show_status : bool, default=True
        Include status badges in node labels
    theme : str, default="default"
        Mermaid theme: 'default', 'forest', 'dark', 'neutral', 'base'
    add_classes : bool, default=True
        Include CSS class definitions for status-based styling
    
    Returns
    -------
    str
        Mermaid flowchart syntax string
    
    Raises
    ------
    VisualizationError
        If tree structure is invalid or file cannot be written
    
    Notes
    -----
    To use in HTML:
    ```html
    <script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
    <script>mermaid.initialize({startOnLoad:true});</script>
    <div class="mermaid">
        <!-- Paste generated code here -->
    </div>
    ```
    
    Examples
    --------
    >>> tree = {
    ...     'name': 'flask',
    ...     'version': '2.3.0',
    ...     'dependencies': [
    ...         {'name': 'werkzeug', 'version': '2.3.0'},
    ...         {'name': 'jinja2', 'version': '3.1.2'}
    ...     ]
    ... }
    
    >>> mermaid_code = export_to_mermaid(tree)
    >>> print(mermaid_code[:100])
    graph LR
        n0["flask (2.3.0)"]
        n1["werkzeug (2.3.0)"]
        n2["jinja2 (3.1.2)"]
    """
    # Validate tree structure
    _validate_tree(tree, "mermaid")
    
    # Initialize styling
    if node_style is None:
        node_style = NodeStyle()
    
    # Normalize direction parameter
    direction_map = {
        'LR': 'LR', 'RL': 'RL', 'TB': 'TB', 'BT': 'BT',
        'left-right': 'LR', 'right-left': 'RL',
        'top-bottom': 'TB', 'bottom-top': 'BT'
    }
    dir_code = direction_map.get(direction.upper(), 'LR')
    
    # Initialize Mermaid graph
    mermaid_lines = [f"graph {dir_code}"]
    
    # Add theme configuration
    if theme != "default":
        mermaid_lines.insert(0, f"%%{{init: {{'theme': '{theme}'}}}}%%")
    
    # Track unique nodes and edges
    node_ids: Dict[str, str] = {}
    edges: List[Tuple[str, str]] = []
    node_counter = 0
    
    def add_mermaid_node(node: Dict, parent_id: Optional[str] = None) -> str:
        """
        Recursively add a node to the Mermaid graph.
        
        Parameters
        ----------
        node : Dict
            Node dictionary (NOT dataclass)
        parent_id : str, optional
            Parent node ID for edge creation
        
        Returns
        -------
        str
            Generated node ID
        """
        nonlocal node_counter
        
        if node is None:
            return ""
        
        # Extract node info using dict methods
        node_name = node.get("name", "unknown")
        node_version = node.get("version", "")
        node_status = node.get("status", "installed")
        
        # Create unique node identifier
        node_key = f"{node_name}|{node_version}"
        
        if node_key not in node_ids:
            node_id = f"n{node_counter}"
            node_counter += 1
            node_ids[node_key] = node_id
            
            # Build node display text
            node_text_parts = [_sanitize_label(node_name, "mermaid")]
            if show_version and node_version:
                node_text_parts.append(f" ({_sanitize_label(node_version, 'mermaid')})")
            if show_status and node_status != "installed":
                status_text = node_status.replace('_', ' ').title()
                node_text_parts.append(f" [{status_text}]")
            
            node_text = "".join(node_text_parts)
            
            # Apply status-based CSS class
            style_class = ""
            if add_classes:
                style_class = node_style.get_mermaid_class(node_status)
            
            # Add node to graph
            mermaid_lines.append(f'    {node_id}["{node_text}"]{style_class}')
        
        # Track edge relationship
        if parent_id is not None:
            edges.append((parent_id, node_ids[node_key]))
        
        # Process dependencies recursively
        dependencies = _collect_dependencies(node)
        for dep in dependencies:
            if isinstance(dep, dict):
                add_mermaid_node(dep, node_ids[node_key])
        
        return node_ids[node_key]
    
    # Process entire tree
    add_mermaid_node(tree)
    
    # Add edges with deduplication
    unique_edges = set(edges)
    for parent, child in sorted(unique_edges):
        mermaid_lines.append(f"    {parent} --> {child}")
    
    # Add CSS class definitions for styling
    if add_classes:
        mermaid_lines.extend([
            "",
            "    classDef default fill:#fff,stroke:#333,stroke-width:2px;",
            f"    classDef not_installed fill:{node_style.not_installed_fill},stroke:#999,stroke-width:1px;",
            f"    classDef error fill:{node_style.error_fill},stroke:#ff0000,stroke-width:2px;",
            f"    classDef cycle fill:{node_style.cycle_fill},stroke:#ffcc00,stroke-width:2px;",
        ])
    
    mermaid_output = "\n".join(mermaid_lines)
    
    # Write to file if requested
    if output_file:
        try:
            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(mermaid_output)
        except IOError as e:
            raise VisualizationError(
                f"Failed to write Mermaid file '{output_file}': {e}",
                format_name="mermaid",
                original_error=e
            )
    
    return mermaid_output


def export_to_html(tree: Dict, output_file: Optional[str] = None,
                  title: str = "Dependency Tree Visualization",
                  interactive: bool = True, theme: str = "light",
                  show_controls: bool = True, max_depth: Optional[int] = None,
                  show_stats: bool = True) -> str:
    """
    Export dependency tree to a self-contained interactive HTML page.
    
    This function generates a COMPLETE HTML document with embedded CSS and
    JavaScript that renders an interactive dependency tree visualization.
    No external dependencies required - works offline in any modern browser.
    
    CRITICAL IMPLEMENTATION NOTES
    -----------------------------
    1. **DICT ACCESS ONLY**: This function processes Python DICTIONARIES.
       ALL access to node properties uses dict syntax (node.get('key'), 
       node['key']). NEVER use attribute access (node.key) as this would 
       require dataclass objects which are NOT supported.
    
    2. **JAVASCRIPT CODE GENERATION**: The function generates JavaScript code
       as Python strings. When writing JS code in Python f-strings:
       - Use {{ for literal { in JavaScript
       - Use concatenation (+) instead of template literals for clarity
       - Always validate that variable names are defined before use
    
    3. **JSON SERIALIZATION**: Tree data is converted to JSON using 
       json.dumps() for embedding in the HTML. Ensure all values are
       JSON-serializable (strings, numbers, lists, dicts, bool, None).
    
    4. **ERROR HANDLING**: The JavaScript code uses defensive programming:
       - Check if elements exist before accessing properties
       - Use && for conditional execution
       - Avoid template literals with complex expressions
    
    Parameters
    ----------
    tree : dict
        Dependency tree as nested dictionary (NOT dataclass)
    output_file : str, optional
        Path to save HTML file. If None, returns string only.
    title : str, default="Dependency Tree Visualization"
        Page title displayed in browser tab and header
    interactive : bool, default=True
        Enable expand/collapse, search, highlighting features
    theme : str, default="light"
        Color theme: 'light' (white bg), 'dark' (dark bg)
    show_controls : bool, default=True
        Show search box and expand/collapse buttons
    max_depth : int, optional
        Limit initial render depth (None = full tree)
    show_stats : bool, default=True
        Show statistics panel (total packages, depth, etc.)
    
    Returns
    -------
    str
        Complete HTML document as string
    
    Raises
    ------
    VisualizationError
        If tree structure is invalid or file cannot be written
    
    Browser Compatibility
    ---------------------
    - Chrome 80+
    - Firefox 75+
    - Safari 13+
    - Edge 80+
    - Mobile browsers (responsive design)
    
    Features
    --------
    - 🌳 Collapsible tree nodes (click arrows)
    - 🔍 Real-time search/filter (highlights matches)
    - 📂 Expand/Collapse all buttons
    - 📊 Statistics panel (total, depth, leaves)
    - 🎨 Color-coded status badges
    - 📱 Responsive design (works on mobile)
    - ⌨️ Keyboard accessible
    - 🌓 Light/Dark theme support
    - 💾 Self-contained (no CDN dependencies)
    
    Examples
    --------
    >>> # Simple usage
    >>> tree = {
    ...     'name': 'myapp',
    ...     'version': '1.0.0',
    ...     'status': 'installed',
    ...     'dependencies': [
    ...         {'name': 'numpy', 'version': '1.24.0', 'status': 'installed'},
    ...         {'name': 'scipy', 'version': '1.10.0', 'status': 'not_installed'}
    ...     ]
    ... }
    
    >>> # Generate and save HTML file
    >>> export_to_html(tree, output_file='dependencies.html', 
    ...               title='My Project Dependencies')
    
    >>> # Get HTML string for web framework
    >>> html = export_to_html(tree, interactive=True, theme='dark')
    >>> # Use in Flask/Django response
    
    >>> # Generate static version without controls
    >>> html = export_to_html(tree, interactive=False, show_controls=False)
    """
    # ===================================================================
    # STEP 1: Validate tree structure
    # ===================================================================
    _validate_tree(tree, "html")
    
    # ===================================================================
    # STEP 2: Prepare tree data for JSON serialization
    # Convert complex types to simple dict structures
    # ===================================================================
    def prepare_tree_data(node: Dict, current_depth: int = 0) -> Dict:
        """
        Recursively prepare tree node for JSON serialization.
        
        IMPORTANT: node is a DICT, not a dataclass.
        Use node.get('key', default) for safe access.
        
        Parameters
        ----------
        node : Dict
            Node dictionary from tree
        current_depth : int
            Current recursion depth
        
        Returns
        -------
        Dict
            Simplified dictionary ready for JSON serialization
        """
        # Check max_depth limit to avoid excessively large outputs
        if max_depth is not None and current_depth >= max_depth:
            return {
                "name": str(node.get("name", "unknown")),
                "version": str(node.get("version", "")),
                "status": str(node.get("status", "installed")),
                "truncated": True
            }
        
        # Build clean node data with all optional fields
        node_data = {
            "name": str(_sanitize_label(node.get("name", "unknown"), "html")),
            "version": str(node.get("version", "")),
            "status": str(node.get("status", "installed")),
            "license": str(node.get("license", "")),
            "homepage": str(node.get("homepage", "")),
            "description": str(node.get("description", "")),
            "depth": current_depth
        }
        
        # Clean up empty optional fields to reduce JSON size
        for key in ["version", "license", "homepage", "description"]:
            if not node_data[key]:
                del node_data[key]
        
        # Recursively process child dependencies
        dependencies = _collect_dependencies(node)
        if dependencies:
            processed_deps = []
            for dep in dependencies:
                if isinstance(dep, dict):
                    processed_deps.append(prepare_tree_data(dep, current_depth + 1))
                # Skip non-dict dependencies silently
            
            if processed_deps:
                node_data["dependencies"] = processed_deps
        
        return node_data
    
    # Prepare the entire tree
    tree_data = prepare_tree_data(tree)
    
    # ===================================================================
    # STEP 3: Define theme colors
    # ===================================================================
    themes = {
        "light": {
            "bg": "#f5f5f5",
            "container": "#ffffff",
            "text": "#333333",
            "border": "#ddd",
            "hover": "#f0f0f0",
            "installed": "#27ae60",
            "not_installed": "#f0f0f0",
            "error": "#e74c3c",
            "cycle": "#f39c12"
        },
        "dark": {
            "bg": "#1e1e1e",
            "container": "#2d2d2d",
            "text": "#e0e0e0",
            "border": "#404040",
            "hover": "#404040",
            "installed": "#6fbf73",
            "not_installed": "#555555",
            "error": "#e74c3c",
            "cycle": "#f39c12"
        }
    }
    
    colors = themes.get(theme, themes["light"])
    
    # ===================================================================
    # STEP 4: Generate HTML with embedded CSS and JavaScript
    # ===================================================================
    
    # Build controls HTML if enabled
    controls_html = ""
    if show_controls:
        controls_html = '''<div class='controls'>
            <input type='text' class='search-box' placeholder='🔍 Search packages...' id='searchInput' oninput='filterTree()'>
            <button onclick='expandAll()'>📂 Expand All</button>
            <button onclick='collapseAll()'>📁 Collapse All</button>
            <button onclick='clearSearch()'>🔄 Clear Search</button>
        </div>'''
    
    # Build stats HTML if enabled
    stats_html = ""
    if show_stats:
        root_name = _sanitize_label(tree.get('name', 'unknown'), 'html')
        stats_html = f'''<div class='stats'>
            <div class='stat-item'>
                <span class='stat-label'>📦 Total Packages:</span>
                <span class='stat-value' id='totalPackages'>0</span>
            </div>
            <div class='stat-item'>
                <span class='stat-label'>📏 Max Depth:</span>
                <span class='stat-value' id='treeDepth'>0</span>
            </div>
            <div class='stat-item'>
                <span class='stat-label'>🌿 Leaf Packages:</span>
                <span class='stat-value' id='leafCount'>0</span>
            </div>
            <div class='stat-item'>
                <span class='stat-label'>📦 Root Package:</span>
                <span class='stat-value'>{root_name}</span>
            </div>
        </div>'''
    
    # Serialize tree data to JSON for embedding in JavaScript
    tree_json = json.dumps(tree_data, ensure_ascii=False, default=str, indent=4)
    
    # Build the complete HTML document
    html_template = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{_sanitize_label(title, 'html')}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        body {{
            font-family: 'Segoe UI', 'Roboto', 'Helvetica Neue', Arial, sans-serif;
            background-color: {colors["bg"]};
            color: {colors["text"]};
            padding: 20px;
            transition: all 0.3s ease;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background-color: {colors["container"]};
            border-radius: 12px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
            overflow: hidden;
        }}
        
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px 30px;
        }}
        
        .header h1 {{
            font-size: 1.8em;
            margin-bottom: 8px;
        }}
        
        .header p {{
            opacity: 0.9;
            font-size: 0.95em;
        }}
        
        .controls {{
            padding: 15px 30px;
            border-bottom: 1px solid {colors["border"]};
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
            align-items: center;
        }}
        
        .search-box {{
            flex: 1;
            min-width: 200px;
            padding: 8px 12px;
            border: 1px solid {colors["border"]};
            border-radius: 6px;
            background-color: {colors["bg"]};
            color: {colors["text"]};
            font-size: 14px;
        }}
        
        .search-box:focus {{
            outline: none;
            border-color: #667eea;
        }}
        
        button {{
            padding: 8px 16px;
            background-color: #667eea;
            color: white;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            transition: background-color 0.2s;
        }}
        
        button:hover {{
            background-color: #5a67d8;
        }}
        
        .stats {{
            padding: 15px 30px;
            background-color: {colors["bg"]};
            border-bottom: 1px solid {colors["border"]};
            display: flex;
            gap: 30px;
            flex-wrap: wrap;
            font-size: 14px;
        }}
        
        .stat-item {{
            display: flex;
            align-items: baseline;
            gap: 8px;
        }}
        
        .stat-label {{
            font-weight: 600;
            opacity: 0.7;
        }}
        
        .stat-value {{
            font-size: 1.2em;
            font-weight: bold;
            color: #667eea;
        }}
        
        .tree-container {{
            padding: 20px 30px;
            overflow-x: auto;
            max-height: 70vh;
            overflow-y: auto;
        }}
        
        .tree-node {{
            margin-left: 25px;
            padding-left: 20px;
            border-left: 2px solid {colors["border"]};
        }}
        
        .tree-root {{
            margin-left: 0;
            border-left: none;
        }}
        
        .tree-item {{
            padding: 8px 12px;
            margin: 4px 0;
            cursor: pointer;
            border-radius: 6px;
            transition: background-color 0.2s;
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }}
        
        .tree-item:hover {{
            background-color: {colors["hover"]};
        }}
        
        .toggle {{
            cursor: pointer;
            user-select: none;
            font-size: 12px;
            width: 20px;
            text-align: center;
            font-weight: bold;
        }}
        
        .package-name {{
            font-weight: 600;
            font-size: 1em;
        }}
        
        .package-version {{
            color: {colors["installed"]};
            font-size: 0.85em;
            font-family: 'Courier New', monospace;
        }}
        
        .package-status {{
            font-size: 0.8em;
            padding: 2px 8px;
            border-radius: 12px;
        }}
        
        .status-not_installed {{
            background-color: {colors["not_installed"]};
            color: #856404;
        }}
        
        .status-error {{
            background-color: {colors["error"]};
            color: white;
        }}
        
        .status-cycle_detected {{
            background-color: {colors["cycle"]};
            color: #856404;
        }}
        
        .children {{
            transition: all 0.3s ease;
        }}
        
        .children.collapsed {{
            display: none;
        }}
        
        .highlight {{
            background-color: rgba(102, 126, 234, 0.2);
            box-shadow: 0 0 0 2px #667eea;
        }}
        
        @media (max-width: 768px) {{
            body {{ padding: 10px; }}
            .controls {{ flex-direction: column; align-items: stretch; }}
            .stats {{ flex-direction: column; gap: 10px; }}
            .tree-item {{ flex-wrap: wrap; }}
        }}
        
        ::-webkit-scrollbar {{ width: 8px; height: 8px; }}
        ::-webkit-scrollbar-track {{ background: #ddd; border-radius: 4px; }}
        ::-webkit-scrollbar-thumb {{ background: #667eea; border-radius: 4px; }}
        ::-webkit-scrollbar-thumb:hover {{ background: #5a67d8; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{_sanitize_label(title, 'html')}</h1>
            <p>Interactive dependency tree visualization - click on arrows to expand/collapse nodes</p>
        </div>
        
        {controls_html}
        {stats_html}
        
        <div class="tree-container">
            <div id="tree"></div>
        </div>
    </div>
    
    <script>
        // Embed tree data directly in page (no AJAX needed)
        var treeData = {tree_json};
        
        // ============================================================
        // Statistics calculation
        // ============================================================
        var totalNodes = 0;
        var maxTreeDepth = 0;
        var leafNodeCount = 0;
        
        function calculateStats(node, depth) {{
            if (depth === undefined) depth = 0;
            
            totalNodes++;
            maxTreeDepth = Math.max(maxTreeDepth, depth);
            
            // Check if this is a leaf node
            if (!node.dependencies || node.dependencies.length === 0) {{
                leafNodeCount++;
            }}
            
            // Recurse into children
            if (node.dependencies) {{
                for (var i = 0; i < node.dependencies.length; i++) {{
                    calculateStats(node.dependencies[i], depth + 1);
                }}
            }}
        }}
        
        calculateStats(treeData);
        
        // Update stats display if elements exist
        var totalEl = document.getElementById('totalPackages');
        var depthEl = document.getElementById('treeDepth');
        var leafEl = document.getElementById('leafCount');
        
        if (totalEl) totalEl.textContent = totalNodes;
        if (depthEl) depthEl.textContent = maxTreeDepth;
        if (leafEl) leafEl.textContent = leafNodeCount;
        
        // ============================================================
        // Tree rendering engine
        // ============================================================
        
        /**
         * Render a dependency tree node and its children recursively.
         * 
         * @param {{Object}} node - Node data object from treeData
         * @param {{HTMLElement}} container - DOM element to attach to
         * @param {{boolean}} isRoot - Whether this is the root node
         * @param {{number}} depth - Current recursion depth
         */
        function renderTree(node, container, isRoot, depth) {{
            if (isRoot === undefined) isRoot = true;
            if (depth === undefined) depth = 0;
            
            // Create main item container
            var itemDiv = document.createElement('div');
            itemDiv.className = 'tree-item';
            itemDiv.setAttribute('data-name', node.name.toLowerCase());
            itemDiv.setAttribute('data-depth', depth);
            
            // Create toggle arrow
            var toggle = document.createElement('span');
            toggle.className = 'toggle';
            
            var hasChildren = node.dependencies && node.dependencies.length > 0;
            if (hasChildren) {{
                toggle.textContent = '▼';
                toggle.style.opacity = '1';
            }} else {{
                toggle.textContent = '•';
                toggle.style.opacity = '0.5';
            }}
            
            // Create package name
            var nameSpan = document.createElement('span');
            nameSpan.className = 'package-name';
            nameSpan.textContent = node.name;
            
            // Create version badge (if version exists)
            var versionSpan = null;
            if (node.version && node.version.length > 0) {{
                versionSpan = document.createElement('span');
                versionSpan.className = 'package-version';
                versionSpan.textContent = '(' + node.version + ')';
            }}
            
            // Create status badge (if not installed)
            var statusSpan = null;
            if (node.status && node.status !== 'installed') {{
                statusSpan = document.createElement('span');
                statusSpan.className = 'package-status status-' + node.status;
                statusSpan.textContent = node.status.replace(/_/g, ' ');
            }}
            
            // Assemble the node
            itemDiv.appendChild(toggle);
            itemDiv.appendChild(nameSpan);
            if (versionSpan) itemDiv.appendChild(versionSpan);
            if (statusSpan) itemDiv.appendChild(statusSpan);
            
            container.appendChild(itemDiv);
            
            // Handle children
            if (hasChildren) {{
                var childrenDiv = document.createElement('div');
                childrenDiv.className = 'children';
                
                // Toggle click handler
                toggle.onclick = function(e) {{
                    e.stopPropagation();
                    if (childrenDiv.style.display === 'none') {{
                        childrenDiv.style.display = 'block';
                        toggle.textContent = '▼';
                    }} else {{
                        childrenDiv.style.display = 'none';
                        toggle.textContent = '▶';
                    }}
                }};
                
                // Render each child
                for (var i = 0; i < node.dependencies.length; i++) {{
                    var childContainer = document.createElement('div');
                    childContainer.className = 'tree-node';
                    renderTree(node.dependencies[i], childContainer, false, depth + 1);
                    childrenDiv.appendChild(childContainer);
                }}
                
                container.appendChild(childrenDiv);
            }}
        }}
        
        // Render the tree
        var treeContainer = document.getElementById('tree');
        var rootDiv = document.createElement('div');
        rootDiv.className = 'tree-root';
        renderTree(treeData, rootDiv, true, 0);
        treeContainer.appendChild(rootDiv);
        
        // ============================================================
        // UI Control Functions
        // ============================================================
        
        /**
         * Expand all collapsed tree nodes.
         */
        function expandAll() {{
            var children = document.querySelectorAll('.children');
            for (var i = 0; i < children.length; i++) {{
                children[i].style.display = 'block';
                var parent = children[i].parentElement;
                if (parent) {{
                    var toggle = parent.querySelector('.toggle');
                    if (toggle) toggle.textContent = '▼';
                }}
            }}
        }}
        
        /**
         * Collapse all expanded tree nodes.
         */
        function collapseAll() {{
            var children = document.querySelectorAll('.children');
            for (var i = 0; i < children.length; i++) {{
                children[i].style.display = 'none';
                var parent = children[i].parentElement;
                if (parent) {{
                    var toggle = parent.querySelector('.toggle');
                    if (toggle && toggle.textContent === '▼') {{
                        toggle.textContent = '▶';
                    }}
                }}
            }}
        }}
        
        /**
         * Clear search and reset tree to default state.
         */
        function clearSearch() {{
            var searchInput = document.getElementById('searchInput');
            if (searchInput) {{
                searchInput.value = '';
            }}
            
            // Remove all highlights
            var items = document.querySelectorAll('.tree-item');
            for (var i = 0; i < items.length; i++) {{
                items[i].style.display = '';
                items[i].classList.remove('highlight');
            }}
            
            // Expand everything
            expandAll();
        }}
        
        /**
         * Filter tree nodes by search term.
         * Highlights matching nodes and collapses non-matching branches.
         */
        function filterTree() {{
            var searchInput = document.getElementById('searchInput');
            if (!searchInput) return;
            
            var searchTerm = searchInput.value.toLowerCase().trim();
            var items = document.querySelectorAll('.tree-item');
            
            for (var i = 0; i < items.length; i++) {{
                var item = items[i];
                var name = item.getAttribute('data-name');
                
                if (searchTerm === '') {{
                    // No search term - show everything
                    item.style.display = '';
                    item.classList.remove('highlight');
                }} else if (name && name.indexOf(searchTerm) !== -1) {{
                    // Match found - show and highlight
                    item.style.display = '';
                    item.classList.add('highlight');
                    
                    // Expand all parent containers to make match visible
                    var parent = item.parentElement;
                    while (parent && parent.classList.contains('children')) {{
                        parent.style.display = 'block';
                        var grandParent = parent.parentElement;
                        if (grandParent) {{
                            var toggle = grandParent.querySelector('.toggle');
                            if (toggle && toggle.textContent === '▶') {{
                                toggle.textContent = '▼';
                            }}
                        }}
                        parent = grandParent;
                    }}
                }} else {{
                    // No match - hide
                    item.style.display = 'none';
                    item.classList.remove('highlight');
                }}
            }}
        }}
    </script>
</body>
</html>'''
    
    # ===================================================================
    # STEP 5: Write to file or return string
    # ===================================================================
    if output_file:
        try:
            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(html_template)
        except IOError as e:
            raise VisualizationError(
                f"Failed to write HTML file '{output_file}': {e}",
                format_name="html",
                original_error=e
            )
    
    return html_template


def export_to_multiple_formats(tree: Dict, output_prefix: str,
                              formats: List[str] = None,
                              **kwargs) -> Dict[str, str]:
    """
    Export dependency tree to multiple visualization formats simultaneously.
    
    Generates multiple output files from a single dependency tree,
    saving time when multiple formats are needed for documentation.
    
    Parameters
    ----------
    tree : Dict
        Dependency tree structure (dictionary, NOT dataclass)
    output_prefix : str
        File path prefix (e.g., 'docs/deps' → docs/deps.html, docs/deps.dot)
    formats : List[str], optional
        Formats to generate: 'graphviz', 'mermaid', 'html'
        Defaults to all three formats
    **kwargs
        Additional keyword arguments passed to each export function
    
    Returns
    -------
    Dict[str, str]
        Mapping of format names to generated file paths
    
    Raises
    ------
    VisualizationError
        If ALL formats fail to generate
    
    Examples
    --------
    >>> tree = {'name': 'myapp', 'dependencies': [{'name': 'numpy'}]}
    >>> files = export_to_multiple_formats(tree, 'output/deps')
    >>> print(files)
    {'graphviz': 'output/deps.dot', 'mermaid': 'output/deps.mmd', 'html': 'output/deps.html'}
    
    >>> # Generate only specific formats
    >>> files = export_to_multiple_formats(tree, 'deps', formats=['html', 'graphviz'])
    """
    if formats is None:
        formats = ['graphviz', 'mermaid', 'html']
    
    format_extensions = {
        'graphviz': '.dot',
        'mermaid': '.mmd',
        'html': '.html'
    }
    
    export_functions = {
        'graphviz': export_to_graphviz,
        'mermaid': export_to_mermaid,
        'html': export_to_html
    }
    
    result = {}
    errors = []
    
    for fmt in formats:
        if fmt not in export_functions:
            errors.append(f"Unknown format: {fmt}")
            continue
        
        output_file = f"{output_prefix}{format_extensions.get(fmt, f'.{fmt}')}"
        
        try:
            export_functions[fmt](tree, output_file=output_file, **kwargs)
            result[fmt] = output_file
        except Exception as e:
            errors.append(f"Failed to generate {fmt}: {str(e)}")
    
    if errors and not result:
        raise VisualizationError(
            f"All formats failed to generate: {'; '.join(errors)}",
            format_name="multiple"
        )
    
    if errors:
        warnings.warn(
            f"Some formats failed: {'; '.join(errors)}",
            UserWarning,
            stacklevel=2
        )
    
    return result


def _check_dependencies() -> None:
    """
    Check for optional system dependencies and warn if missing.
    
    Graphviz is required for rendering DOT files but not for generating
    the DOT source code. Users can render DOT files online if Graphviz
    is not installed locally.
    """
    try:
        import shutil
        if shutil.which('dot') is None:
            warnings.warn(
                "Graphviz 'dot' executable not found in PATH. "
                "Install Graphviz to render DOT files: https://graphviz.org/download/",
                UserWarning,
                stacklevel=2
            )
    except ImportError:
        # shutil not available (very rare), skip the check
        pass


# Run dependency check on module import
_check_dependencies()