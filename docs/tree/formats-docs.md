# PyPUtil Dependency Visualization Module

## Overview

PyUtil Dependency Visualization provides comprehensive tools for transforming dependency trees into multiple visual and structured formats. It generates interactive HTML diagrams, Graphviz DOT files, Mermaid diagrams, and structured outputs (JSON/YAML/DICT) for documentation, debugging, and integration with other tools.

## Why Use This Module?

| Use Case | Solution |
|----------|----------|
| **Documentation** | Embed dependency diagrams in README files using Mermaid |
| **CI/CD Pipelines** | Generate Graphviz diagrams for build reports |
| **Web Applications** | Interactive HTML explorer with search/filter |
| **Data Analysis** | JSON/YAML structured output for processing |
| **Team Communication** | Share visual dependency trees with non-technical stakeholders |

## Architecture

```

┌─────────────────────────────────────────────────────────────┐
│                    Dependency Tree (Dict)                    │
└─────────────────────────────────────────────────────────────┘
│
┌─────────────────────┼─────────────────────┐
▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│   HTML Export  │    │  Graphviz DOT  │    │   Mermaid      │
│  (Interactive) │    │  (Static SVG)  │    │  (Web Native)  │
└───────────────┘    └───────────────┘    └───────────────┘
│                     │                     │
▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│   Structured   │    │   Requirements │    │   Constraints  │
│  (JSON/YAML)   │    │   (pip format) │    │   (pip format) │
└───────────────┘    └───────────────┘    └───────────────┘

```

## Core Functions

### 1. HTML Export (`export_to_html`)

**Purpose**: Generate a complete, self-contained interactive web page for exploring dependency trees.

**Key Features**:
- 🔍 Real-time search and filtering
- 📂 Expand/collapse all nodes
- 📊 Statistics panel (total packages, depth, leaf count)
- 🎨 Light/dark theme support
- 📱 Responsive design (works on mobile)
- 💾 No external dependencies (self-contained)

**Usage Example**:

```python
from pyputil.tree.formats import export_to_html

# Sample dependency tree
tree = {
    'name': 'myapp',
    'version': '1.0.0',
    'status': 'installed',
    'dependencies': [
        {
            'name': 'requests',
            'version': '2.28.1',
            'status': 'installed',
            'dependencies': [
                {'name': 'urllib3', 'version': '1.26.13', 'status': 'installed'},
                {'name': 'certifi', 'version': '2022.12.7', 'status': 'installed'}
            ]
        },
        {
            'name': 'numpy',
            'version': '1.24.0',
            'status': 'not_installed'
        }
    ]
}

# Generate interactive HTML (saves to file)
export_to_html(tree, output_file='deps.html', title='My Project Dependencies')

# Get HTML string for embedding in web app
html_content = export_to_html(tree, interactive=True, theme='dark')
```

2. Graphviz Export (export_to_graphviz)

Purpose: Generate professional static diagrams for documentation and reports.

Key Features:

· 🎨 Customizable node styling (colors, shapes)
· 📐 Multiple layout directions (LR, TB, RL, BT)
· 🔧 Fine-grained control (ranksep, nodesep)
· 📄 Save as .dot file for rendering

Rendering Commands:

```bash
# Generate PNG
dot -Tpng deps.dot -o deps.png

# Generate SVG (web-friendly)
dot -Tsvg deps.dot -o deps.svg

# Generate PDF (documentation)
dot -Tpdf deps.dot -o deps.pdf
```

Usage Example:

```python
from pyputil.tree.formats import export_to_graphviz, NodeStyle

# Custom styling
style = NodeStyle(
    installed_fill="#e8f5e9",      # Green for installed
    not_installed_fill="#f5f5f5", # Gray for missing
    error_fill="#ffebee",          # Red for errors
    cycle_fill="#fff8e1",          # Yellow for cycles
    font_color="#333333",
    font_size=12
)

# Generate DOT with custom layout
dot_code = export_to_graphviz(
    tree,
    output_file='deps.dot',
    rankdir='TB',          # Top to bottom layout
    node_style=style,
    show_version=True,
    show_status=True,
    ranksep=0.5,
    nodesep=0.3
)
```

3. Mermaid Export (export_to_mermaid)

Purpose: Generate diagrams that render natively in GitHub/GitLab markdown and documentation sites.

Key Features:

· 📝 GitHub/GitLab markdown compatible
· 🎨 Theme support (default, forest, dark, neutral)
· 🔗 Works with MkDocs, Sphinx, and online editors
· 📱 Browser-native (JavaScript-based)

Usage Example:

```python
from pyputil.tree.formats import export_to_mermaid

# Generate Mermaid diagram
mermaid_code = export_to_mermaid(
    tree,
    output_file='deps.mmd',
    direction='TB',
    theme='forest',
    show_version=True,
    show_status=True
)

# In your Markdown file:
# ```mermaid
# graph TB
#     n0["myapp (1.0.0)"]
#     n1["requests (2.28.1)"]
#     n2["numpy (1.24.0) :::not_installed"]
#     n0 --> n1
#     n0 --> n2
# ```
```

4. Structured Output (format_output)

Purpose: Convert dependency trees to JSON, YAML, or Python dict for programmatic consumption.

Key Features:

· 🔄 Multiple formats (JSON, YAML, DICT)
· 🎯 Field filtering (include/exclude)
· 📊 Pretty-printing with configurable indentation
· 🔒 Thread-safe and secure

Usage Example:

```python
from pyputil.tree.formats import format_output, OutputFormat
from pyputil.tree.formats import filter_tree_output, FieldFilter

# JSON output (pretty)
json_str = format_output(tree, OutputFormat.JSON, indent=2)

# YAML output with line wrapping
yaml_str = format_output(
    tree,
    OutputFormat.YAML,
    indent=2,
    line_width=80,
    explicit_start=True
)

# Python dict (fastest, no conversion)
dict_obj = format_output(tree, OutputFormat.DICT)

# Filter fields before output
filtered = filter_tree_output(
    tree,
    include_fields=['name', 'version', 'dependencies.name'],
    max_depth=2,
    max_items=10
)
```

5. Requirements Conversion (tree_to_requirements)

Purpose: Convert dependency tree to pip-compatible requirements.txt format.

Usage Example:

```python
from pyputil.tree.formats import tree_to_requirements, tree_to_pip_constraints

# Generate requirements.txt
req_text = tree_to_requirements(
    tree,
    include_extras=True,
    include_markers=True,
    upgrade_versions=False   # Use == for exact pins
)

# Generate constraints.txt
constraints = tree_to_pip_constraints(tree, upgrade_versions=True)
```

6. Multiple Formats Export (export_to_multiple_formats)

Purpose: Generate all visualization formats in a single call.

Usage Example:

```python
from pyputil.tree.formats import export_to_multiple_formats

# Generate HTML, DOT, and Mermaid simultaneously
files = export_to_multiple_formats(
    tree,
    output_prefix='docs/deps',
    formats=['html', 'graphviz', 'mermaid'],
    title='Project Dependencies',
    rankdir='TB'
)

print(f"HTML: {files['html']}")      # docs/deps.html
print(f"Graphviz: {files['graphviz']}")  # docs/deps.dot
print(f"Mermaid: {files['mermaid']}")    # docs/deps.mmd
```

7. Tree Utilities

Purpose: Helper functions for tree manipulation and validation.

Usage Example:

```python
from pyputil.tree.formats import (
    validate_tree_structure,
    merge_trees,
    get_stats,
    filter_tree_output
)

# Validate tree
errors = validate_tree_structure(tree, strict=True)
if errors:
    print(f"Validation errors: {errors}")

# Merge two trees
merged = merge_trees(tree1, tree2, strategy='recursive')

# Get statistics
stats = get_stats(tree)
print(f"Total dependencies: {stats['total_dependencies']}")
print(f"Max depth: {stats['max_depth']}")
print(f"Unique packages: {stats['unique_packages']}")
```

NodeStyle Customization

The NodeStyle class provides comprehensive styling control:

```python
from pyputil.tree.formats import NodeStyle

# Custom dark theme
dark_style = NodeStyle(
    default_fill="#2d2d2d",
    default_stroke="#667eea",
    installed_fill="#1a472a",     # Dark green
    not_installed_fill="#3d3d3d",  # Dark gray
    error_fill="#4a1a1a",          # Dark red
    cycle_fill="#4a3a1a",          # Dark yellow
    font_color="#ffffff",
    font_size=14
)

# Light theme with green accents
light_style = NodeStyle(
    installed_fill="#e8f5e9",
    not_installed_fill="#f5f5f5",
    error_fill="#ffebee",
    cycle_fill="#fff8e1"
)
```

Complete Example

```python
#!/usr/bin/env python3
"""Complete dependency visualization example."""

from pyputil.tree.formats import (
    export_to_html, export_to_graphviz, export_to_mermaid,
    export_to_multiple_formats, format_output, OutputFormat,
    NodeStyle, filter_tree_output
)

# Sample dependency tree
tree = {
    'name': 'myapp',
    'version': '1.0.0',
    'status': 'installed',
    'description': 'Main application',
    'dependencies': [
        {
            'name': 'requests',
            'version': '2.28.1',
            'status': 'installed',
            'license': 'Apache-2.0',
            'dependencies': [
                {'name': 'urllib3', 'version': '1.26.13', 'status': 'installed'},
                {'name': 'certifi', 'version': '2022.12.7', 'status': 'installed'},
                {'name': 'idna', 'version': '3.4', 'status': 'installed'}
            ]
        },
        {
            'name': 'pandas',
            'version': '1.5.3',
            'status': 'installed',
            'extras': ['computation'],
            'dependencies': [
                {'name': 'numpy', 'version': '1.24.0', 'status': 'installed'},
                {'name': 'python-dateutil', 'version': '2.8.2', 'status': 'installed'}
            ]
        },
        {
            'name': 'unavailable-pkg',
            'version': '',
            'status': 'not_installed',
            'requirement': '>=2.0.0'
        }
    ]
}

def generate_all_visualizations(tree, output_base='docs/deps'):
    """Generate all visualization formats from a dependency tree."""
    
    print(f"Generating visualizations for dependency tree...")
    
    # 1. Interactive HTML (for developers)
    export_to_html(
        tree,
        output_file=f'{output_base}.html',
        title='Project Dependency Tree',
        interactive=True,
        theme='light',
        show_controls=True,
        show_stats=True
    )
    print(f"  ✓ HTML: {output_base}.html")
    
    # 2. Graphviz DOT (for static diagrams)
    style = NodeStyle(
        installed_fill="#e8f5e9",
        not_installed_fill="#f5f5f5",
        error_fill="#ffebee"
    )
    export_to_graphviz(
        tree,
        output_file=f'{output_base}.dot',
        rankdir='TB',
        node_style=style,
        show_version=True,
        show_status=True
    )
    print(f"  ✓ Graphviz: {output_base}.dot")
    
    # 3. Mermaid (for markdown)
    export_to_mermaid(
        tree,
        output_file=f'{output_base}.mmd',
        direction='TB',
        theme='forest',
        show_version=True,
        show_status=True
    )
    print(f"  ✓ Mermaid: {output_base}.mmd")
    
    # 4. JSON (for data processing)
    json_str = format_output(tree, OutputFormat.JSON, indent=2)
    with open(f'{output_base}.json', 'w') as f:
        f.write(json_str)
    print(f"  ✓ JSON: {output_base}.json")
    
    # 5. Filtered output (for documentation)
    filtered = filter_tree_output(
        tree,
        include_fields=['name', 'version', 'status'],
        max_depth=2
    )
    yaml_str = format_output(filtered, OutputFormat.YAML, indent=2)
    with open(f'{output_base}_filtered.yaml', 'w') as f:
        f.write(yaml_str)
    print(f"  ✓ YAML: {output_base}_filtered.yaml")
    
    print("\nVisualization complete!")

# Run the example
if __name__ == "__main__":
    generate_all_visualizations(tree)
```

Requirements

· Python 3.7+
· No external dependencies for core functionality
· Optional: PyYAML for full YAML support
· Optional: Graphviz for rendering DOT files (command-line tool)

Key Features Summary

Feature HTML Graphviz Mermaid Structured
Interactive ✓ ✗ ✗ ✗
Search/Filter ✓ ✗ ✗ ✗
Print/Export ✓ ✓ ✓ ✓
GitHub Markdown ✗ ✗ ✓ ✗
Custom Styling ✓ ✓ ✓ ✗
Theme Support ✓ ✗ ✓ ✗
JSON/YAML Output ✗ ✗ ✗ ✓
Requirements.txt ✗ ✗ ✗ ✓
Self-contained ✓ ✓ ✗ ✓