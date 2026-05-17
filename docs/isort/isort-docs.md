# Import Sorter (isort) Documentation

## Overview

Import Sorter (isort) is a comprehensive Python utility for parsing, organizing, sorting, and formatting import statements in Python files. It automatically categorizes imports into logical sections (future, standard library, third-party, first-party, local), sorts them alphabetically, and applies configurable formatting rules.

## Architecture

The system consists of the following core modules:

| Module | Purpose |
|--------|---------|
| `config.py` | Configuration classes and constants |
| `models.py` | Data models for import statements and sections |
| `parser.py` | Import statement parser with regex and AST support |
| `formatter.py` | Import statement formatter with multiple styles |
| `processor.py` | Main processor coordinating the sorting workflow |
| `fixer.py` | Import fixer for detecting and fixing common issues |

## Quick Start

```python
from pyputil.isort import ImportProcessor

# Basic usage
processor = ImportProcessor()
success, message, imports = processor.process_file("my_module.py")
print(message)  # "Successfully sorted imports in my_module.py"
```

Core Classes

1. ImportConfig

Configuration for import sorting behavior.

Parameters:

Parameter Type Default Description
line_length int 79 Maximum line length for imports
multi_line_output int 3 Style for multi-line imports (0-6)
include_trailing_comma bool False Include trailing comma in multi-line imports
force_grid_wrap int 0 Force grid wrap for imports with N items
use_parentheses bool True Use parentheses for multi-line imports
ensure_newline_before_comments bool True Ensure newline before inline comments
sections List[str] ['FUTURE', 'STANDARD', 'THIRD_PARTY', 'FIRST_PARTY', 'LOCAL'] Order of import sections
known_standard_library Set[str] Built-in stdlib set Known standard library modules
known_third_party Set[str] Empty Known third-party packages
known_first_party Set[str] Empty Known first-party modules

Multi-line Output Styles:

Value Style Description
0 Inline All imports on one line
1 Grid Each import on new line with parentheses
2 Vertical Grid Similar to grid but with hanging indent
3 Hanging Grid Hanging indent with parentheses
4 Vertical Hanging Vertical alignment with hanging indent
5 Hanging Indent Traditional hanging indent
6 No Parentheses No parentheses, use backslashes

Examples:

```python
from pyputil.isort import ImportConfig

# Create custom configuration
config = ImportConfig(
    line_length=120,
    multi_line_output=4,  # Vertical hanging indent
    include_trailing_comma=True,
    known_third_party={'requests', 'numpy', 'pandas'},
    known_first_party={'myproject', 'utils'}
)

# Load from pyproject.toml
config.load_from_file("pyproject.toml")
```

2. ImportStatement

Data model representing a single import statement.

Attributes:

Attribute Type Description
raw_statement str Original import statement as string
line_number int Line number where import was found
import_type ImportType Type of import (standard, third-party, etc.)
module str Module name being imported
is_from_import bool True if 'from ... import ...' statement
names List[str] List of imported names (for 'from' imports)
alias Optional[str] Alias name if using 'as' keyword
comments List[str] Inline and trailing comments
indent str Indentation of the import statement

3. ImportSections

Container for organized import statements by section.

Section Order (default):

1. FUTURE - __future__ imports
2. STANDARD - Standard library imports
3. THIRD_PARTY - Third-party package imports
4. FIRST_PARTY - Current project imports
5. LOCAL - Local/relative imports

4. ImportParser

Parser for extracting import statements from Python code.

Methods:

Method Description
parse_file(filepath) Parse Python file and extract imports
parse_content(content, filepath) Parse Python code content

Example:

```python
from pyputil.isort import ImportConfig, ImportParser

config = ImportConfig()
parser = ImportParser(config)

# Parse file
imports = parser.parse_file("my_module.py")

for imp in imports:
    print(f"Line {imp.line_number}: {imp.raw_statement}")
    print(f"  Type: {imp.import_type.name}")
    print(f"  Module: {imp.module}")
```

5. ImportFormatter

Formatter for applying configuration rules to import statements.

Example:

```python
from pyputil.isort import ImportConfig, ImportFormatter, ImportSections

config = ImportConfig(multi_line_output=4, use_parentheses=True)
formatter = ImportFormatter(config)

# Format sections into lines
formatted_lines = formatter.format_sections(sections)

# Or format single statement
formatted = formatter.format_statement(import_statement)
```

6. ImportProcessor

Main processor coordinating the entire sorting workflow.

Methods:

Method Description
process_file(filepath, in_place, backup) Process single Python file
process_dir(directory, recursive, in_place, backup) Process all Python files in directory
check_file(filepath) Check if imports are already sorted

Usage Examples

Basic File Processing

```python
from pyputil.isort import ImportProcessor

processor = ImportProcessor()

# Process file in place
success, message, imports = processor.process_file("my_module.py")

if success:
    print(message)
    print(f"Found {len(imports)} imports")
else:
    print(f"Error: {message}")
```

Processing with Backup

```python
# Create backup before modifying
success, message, imports = processor.process_file(
    "my_module.py",
    in_place=True,
    backup=True  # Creates my_module.py.bak
)
```

Check Without Modifying

```python
# Check if imports are already sorted
is_sorted, issues = processor.check_file("my_module.py")

if not is_sorted:
    print("Import issues found:")
    for issue in issues:
        print(f"  - {issue}")
else:
    print("Imports are properly sorted!")
```

Process Entire Directory

```python
# Process all Python files in directory
results = processor.process_dir(
    "./src",
    recursive=True,
    in_place=True,
    backup=False
)

for filepath, result in results.items():
    if result['success']:
        print(f"✓ {filepath}: {result['imports_count']} imports sorted")
    else:
        print(f"✗ {filepath}: {result['message']}")
```

Custom Configuration

```python
from pyputil.isort import ImportProcessor, ImportConfig

# Create custom configuration
config = ImportConfig(
    line_length=100,
    multi_line_output=4,  # Vertical hanging indent
    include_trailing_comma=True,
    use_parentheses=True,
    sections=["FUTURE", "STANDARD", "THIRD_PARTY", "FIRST_PARTY", "LOCAL"],
    known_third_party={"requests", "numpy", "pandas"},
    known_first_party={"myapp", "utils", "models"}
)

# Use custom configuration
processor = ImportProcessor(config)
processor.process_file("my_module.py")
```

Loading Configuration from File

```python
# pyproject.toml
"""
[tool.import_sorter]
line_length = 100
multi_line_output = 4
include_trailing_comma = true
use_parentheses = true
known_third_party = ["requests", "numpy", "pandas"]
known_first_party = ["myapp", "utils"]
"""

from pyputil.isort import ImportConfig

config = ImportConfig()
config.load_from_file("pyproject.toml")
```

Import Fixer

The ImportFixer class detects and fixes common import issues.

Detected Issues:

Issue Description
Duplicate imports Same module imported multiple times
Incorrect indentation Tabs instead of spaces, non-multiple of 4
Multiple same module Several imports from same module on separate lines
Mixed styles Simple and from imports interleaved
Unorganized Imports not grouped by type
Syntax errors Malformed import statements

Example:

```python
from pyputil.isort import ImportFixer

fixer = ImportFixer("my_module.py")

# Load file and parse imports
if fixer.load_file():
    fixer.init()
    
    # Detect issues
    issues = fixer.detect_issues()
    
    for issue_type, issue_list in issues.items():
        if issue_list:
            print(f"{issue_type}: {len(issue_list)} issues found")
            for issue in issue_list:
                print(f"  Line {issue.line}: {issue.message or issue.issue}")
    
    # Fix imports
    fixed_content = fixer.fix_imports()
    
    # Save fixed file
    if fixer.save_fixed_file():
        print("File fixed successfully!")
```

Input/Output Examples

Before Sorting

```python
# messy_imports.py
import sys, os
from .utils import helper
import pandas as pd
from datetime import datetime
import numpy as np
from myproject.database import connect
import requests
from __future__ import print_function
```

After Sorting

```python
# organized_imports.py
from __future__ import print_function

import datetime
import os
import sys

import numpy as np
import pandas as pd
import requests

from myproject.database import connect

from .utils import helper
```

Multi-line Import Formatting

```python
# Before
from myproject.utils import (
    helper1, helper2, helper3, helper4, helper5, helper6, helper7, helper8,
    helper9, helper10
)

# After (with multi_line_output=4, include_trailing_comma=True)
from myproject.utils import (
    helper1,
    helper2,
    helper3,
    helper4,
    helper5,
    helper6,
    helper7,
    helper8,
    helper9,
    helper10,
)
```

Import Type Classification

The parser automatically classifies imports using multiple strategies:

1. Future Imports: from __future__ import ...
2. Standard Library: Matches against built-in stdlib set
3. Relative/Local: Starts with . (e.g., from .module import x)
4. First Party: Matches known_first_party set or files in project root
5. Third Party: Everything else (default)

Complete Example

```python
#!/usr/bin/env python3
"""Example script using Import Sorter."""

from pathlib import Path
from pyputil.isort import (
    ImportProcessor,
    ImportConfig,
    ImportFixer,
    ImportType
)

def main():
    """Sort imports in all Python files in current directory."""
    
    # Create configuration
    config = ImportConfig(
        line_length=100,
        multi_line_output=4,
        include_trailing_comma=True,
        known_third_party={"requests", "click", "colorama"},
        known_first_party={"myapp"}
    )
    
    # Create processor
    processor = ImportProcessor(config)
    
    # Process all Python files
    results = processor.process_dir(
        directory=".",
        recursive=True,
        in_place=True,
        backup=True
    )
    
    # Display results
    success_count = sum(1 for r in results.values() if r['success'])
    total_count = len(results)
    
    print(f"Processed {total_count} files")
    print(f"Successfully sorted: {success_count}")
    
    # Show failed files
    failed = [f for f, r in results.items() if not r['success']]
    if failed:
        print("\nFailed files:")
        for f in failed:
            print(f"  - {f}: {results[f]['message']}")

if __name__ == "__main__":
    main()
```

Requirements

· Python 3.7+
· Standard library only for core functionality
· Optional: tomli for pyproject.toml support (Python <3.11)
· Optional: configparser for .cfg/.ini support

Key Features Summary

Feature Description
Auto-categorization Automatically classifies imports into sections
Multiple styles 7 different multi-line formatting styles
Configurable Extensive configuration options
File support Single file or entire directory processing
AST parsing Accurate import extraction using AST
Backup support Automatic backup before modifications
Issue detection Finds duplicate, misordered, and malformed imports
Dry run Check without modifying files
Project root detection Automatically identifies first-party modules
Comment preservation Preserves inline and trailing comments