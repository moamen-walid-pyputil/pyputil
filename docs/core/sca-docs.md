# PyPutil Core SCA (Static Code Analysis) Documentation

## Overview

PyPutil Core SCA is a comprehensive Python static and dynamic code analysis framework that provides multiple parsers for different levels of code inspection. It supports source code strings, file paths, and live Python objects, offering a unified interface for all analysis needs.

## Architecture

The system consists of four specialized parsers and a unified entry point:

| Module | Purpose |
|--------|---------|
| `_string_parser.py` | Regex-based static source code analysis |
| `_code_parser.py` | Bytecode-level structural analysis |
| `_source_parser.py` | Source file extraction and manipulation |
| `_object_parser.py` | Runtime object introspection |
| `__init__.py` | Unified `Source()` function interface |

## Parser Comparison

| Parser | Analysis Level | Best For | Input Type | Performance |
|--------|---------------|----------|------------|-------------|
| `StringParser` | Source code (regex) | Static patterns, imports, simple structure | Source string | Fast |
| `CodeParser` | Bytecode | Deep structure, control flow, complexity | Source string | Moderate |
| `SourceParser` | Source file | File operations, source extraction | File path or object | Moderate |
| `ObjectParser` | Runtime | Live object introspection, metadata | Python object | Fast |

## Unified Interface: `Source()`

The main entry point that automatically selects and initializes the appropriate parser.

### Function Signature

```python
def Source(
    obj: Any,
    parser: str = "source.parser",
    target: Optional[str] = None,
) -> Union[StringParser, CodeParser, SourceParser, ObjectParser]
```

Parameters

Parameter Type Default Description
obj Any Required Input data (source code, file path, or Python object)
parser str "source.parser" Parser type: "string.parser", "code.parser", "source.parser", "object.parser"
target Optional[str] None Input interpretation: "source", "file", "object" (auto-detected if None)

Returns

· StringParser for parser="string.parser"
· CodeParser for parser="code.parser"
· SourceParser for parser="source.parser"
· ObjectParser for parser="object.parser"

Target Auto-Detection

When target=None (default):

1. If parser="object.parser" → target="object"
2. If obj is an existing .py file path → target="file" (with warning)
3. Otherwise → target="source"

Usage Examples

Basic Usage with Source Code

```python
from pyputil.core.sca import Source

code = '''
def calculate_average(numbers: list) -> float:
    """Calculate the average of a list of numbers."""
    if not numbers:
        return 0.0
    total = sum(numbers)
    return total / len(numbers)
'''

# Using StringParser (regex-based)
parser = Source(code, parser="string.parser")
functions = parser.functions()
print(functions[0].name)  # 'calculate_average'
print(functions[0].parameters)  # 'numbers: list'
print(functions[0].return_type)  # 'float'
print(functions[0].docstring)    # 'Calculate the average...'

# Using CodeParser (bytecode analysis)
parser = Source(code, parser="code.parser")
result = parser.analyze()
print(result.functions[0].name)  # 'calculate_average'
print(result.functions[0].argcount)  # 1
print(result.metrics.cyclomatic_complexity)  # 2
```

File Analysis

```python
from pyputil.core.sca import Source

# Auto-detect file (with warning)
parser = Source("/path/to/my_module.py")  # doctest: +SKIP

# Explicit file mode
parser = Source("/path/to/my_module.py", target="file")  # doctest: +SKIP

# Get source information
print(parser.file)  # '/path/to/my_module.py'
print(parser.line_count)  # 150
print(parser.source[:100])  # First 100 chars

# Extract functions and classes
functions = parser.functions()
classes = parser.classes()
imports = parser.imports()
```

Live Object Introspection

```python
from pyputil.core.sca import Source
import math

# Introspect module
parser = Source(math, parser="object.parser")
print(parser.type_name)  # 'module'
print('sqrt' in parser.attrs)  # True
print(len(parser.functions()))  # Number of functions
print(len(parser.variables()))  # Number of variables

# Introspect class
class MyClass:
    class_var: int = 100
    
    def __init__(self, name: str):
        self.name = name
    
    @property
    def display(self) -> str:
        return f"Item: {self.name}"
    
    @staticmethod
    def helper():
        pass
    
    def _private_method(self):
        pass

parser = Source(MyClass, parser="object.parser")
print(parser.methods())        # ['_private_method', 'display']
print(parser.properties())     # ['display']
print(parser.staticmethods())  # ['helper']
print(parser.private())        # ['_private_method']
print(parser.annotations())    # {'class_var': <class 'int'>}
```

Source Code Extraction

```python
from pyputil.core.sca import Source

def example_function(x: int, y: str = "default") -> bool:
    """Example function documentation."""
    return x > 0

parser = Source(example_function, parser="source.parser", target="object")

# Extract source
print(parser.name)  # 'example_function'
print(parser.source)  # Full source code
print(parser.line_count)  # Number of lines
print(parser.args)  # [('example_function', ['x', 'y'])]
print(parser.hints)  # {'example_function': {'x': 'int', 'y': 'str', 'return': 'bool'}}
print(parser.docstrings_only)  # [(line, 'Example function documentation.')]

# Save to file
parser.sdump("/tmp/example.py")  # doctest: +SKIP
```

Convenience Functions

```python
from pyputil.core.sca import (
    parse_string,
    parse_code,
    parse_file,
    parse_object
)

# Parse source code string
parser = parse_string("x = 42")
print(parser.variables())  # ['x']

# Parse with bytecode analysis
parser = parse_code("def add(a, b): return a + b")
result = parser.analyze()
print(result.functions[0].name)  # 'add'

# Parse file
parser = parse_file("/path/to/module.py")  # doctest: +SKIP
print(parser.file)  # '/path/to/module.py'

# Parse live object
import sys
parser = parse_object(sys)
print(len(parser.attrs))  # Many attributes
```

Parser-Specific Documentation

1. StringParser (Regex-Based Static Analysis)

Best for: Fast static analysis of source code patterns, imports, variables, and simple structure.

Key Methods:

Method Description
functions() Extract function definitions with metrics
classes() Extract class definitions with methods
imports() Extract import statements
variables() Extract variable assignments
function_calls() Extract function/method calls
code_issues() Detect code quality issues
security_vulnerabilities() Detect security vulnerabilities
deps() Analyze dependencies
summary() Generate comprehensive summary
to_json() Export results as JSON

Example:

```python
from pyputil.core.sca import parse_string

code = """
import os
from pathlib import Path

def process(data: list) -> bool:
    if not data:
        return False
    for item in data:
        if item > 0:
            print(item)
    return True

class Processor:
    def __init__(self):
        self.items = []
    
    def add(self, item):
        self.items.append(item)
"""

parser = parse_string(code)

# Function analysis
functions = parser.functions()
for f in functions:
    print(f"{f.name}: complexity={f.metrics.cyclomatic_complexity}")

# Class analysis
classes = parser.classes()
for c in classes:
    print(f"{c.name}: {len(c.methods)} methods")

# Imports
for imp in parser.imports():
    print(f"{imp.import_type}: {imp.module}")

# Code issues
for issue in parser.code_issues():
    print(f"[{issue.severity.value}] {issue.description}")

# Security vulnerabilities
for vuln in parser.security_vulnerabilities():
    print(f"[{vuln.cwe_id}] {vuln.description}")

# Dependency graph
for dep in parser.deps():
    print(f"{dep.source} -> {dep.target} ({dep.dependency_type})")
```

Metrics Returned by FunctionInfo:

Attribute Description
line_count Number of executable lines
cyclomatic_complexity McCabe complexity score
parameter_count Number of parameters
nested_depth Maximum nesting level
cognitive_complexity Cognitive complexity score
maintainability_index 0-100 scale (higher is better)
comment_ratio Comment lines / code lines

2. CodeParser (Bytecode Analysis)

Best for: Deep structural analysis, control flow detection, exception handling, and accurate complexity metrics.

Key Methods:

Method Description
analyze() Perform complete bytecode analysis
search(pattern, category) Search for patterns in analyzed code

AnalysisResult Attributes:

Attribute Description
functions List of FunctionInfo (bytecode analysis)
classes List of ClassInfo
calls List of CallInfo (function/method calls)
imports List of ImportInfo
variables List of VariableInfo
attribute_accesses List of AttributeAccessInfo
control_flow List of ControlFlowInfo
exceptions List of ExceptionInfo
comprehensions List of ComprehensionInfo
context_managers List of ContextManagerInfo
metrics CodeMetrics (complexity, maintainability)

Example:

```python
from pyputil.core.sca import parse_code

code = """
def complex_function(x):
    try:
        if x > 0:
            for i in range(x):
                if i % 2 == 0:
                    yield i
        else:
            with open('file.txt') as f:
                data = f.read()
    except Exception as e:
        print(f"Error: {e}")
    finally:
        print("Done")
"""

parser = parse_code(code)
result = parser.analyze()

print(f"Functions: {len(result.functions)}")
print(f"Control flow: {len(result.control_flow)}")
print(f"Exceptions: {len(result.exceptions)}")
print(f"Context managers: {len(result.context_managers)}")
print(f"Comprehensions: {len(result.comprehensions)}")
print(f"Cyclomatic complexity: {result.metrics.cyclomatic_complexity}")

# Search for patterns
matches = parser.search("exception", category="all")
print(matches)  # {'exceptions': ['ExceptionInfo...']}
```

ControlFlowType Enum:

Value Description
JUMP Unconditional jump
CONDITIONAL Conditional branch (if, elif)
LOOP Loop iteration (for, while)
EXCEPTION Exception handling setup
CONTEXT_MANAGER Context manager setup (with)

3. SourceParser (Source File Analysis)

Best for: Source code extraction, file operations, code transformation, and static analysis with line numbers.

Key Properties/Methods:

Method Description
source Dedented source code
file Source file path
line_count Number of lines
functions() Extract function definitions
classes() Extract class definitions
imports() Extract import statements
variables() Extract variable names
decorators Extract decorator information
hints Extract type hints
docs Extract docstrings
calls Extract function calls
exceptions Extract try-except blocks
inheritance Extract class inheritance
comments Extract comments
constants Extract constant values
complexity Complexity metrics
cyclomatic_complexity McCabe complexity
minify Minify source code
sdump() Save source code to file
fdump() Save full source file
freplace() Find and replace in file
diff() Generate diff between sources

Example:

```python
from pyputil.core.sca import Source, parse_file

# From file
parser = parse_file("/path/to/module.py")  # doctest: +SKIP

print(f"File: {parser.file}")
print(f"Lines: {parser.line_count}")
print(f"Functions: {parser.defs}")
print(f"Classes: {parser.classes}")
print(f"Imports: {parser.imports}")
print(f"Variables: {parser.variables}")
print(f"Cyclomatic complexity: {parser.cyclomatic_complexity}")

# Extract docstrings
for name, doc in parser.docs:
    if doc:
        print(f"{name}: {doc[:50]}...")

# Extract comments
for comment, (line, col) in parser.comments:
    print(f"Line {line}: {comment}")

# Get specific function body
body = parser.getbody("calculate")
if body:
    print(body)

# Find unreachable code
for line, code in parser.unreachable_code:
    print(f"Unreachable at line {line}: {code}")
```

4. ObjectParser (Runtime Introspection)

Best for: Live object analysis, attribute categorization, and runtime metadata extraction.

Key Methods:

Method Description
functions() User-defined functions
methods() Bound methods
builtins() Built-in functions
classes() Nested classes
variables() Data attributes
properties() @property decorators
staticmethods() @staticmethod decorators
classmethods() @classmethod decorators
descriptors() Descriptor protocol objects
magic_methods() Dunder methods (init, str, etc.)
private() Protected attributes (_prefix)
name_mangled() Name-mangled attributes (__prefix)
slots() slots attributes
annotations() Type annotations
inheritance() MRO chain
abstract_methods() Abstract methods (ABC)
body() Source code of attribute
signature() Callable signature
summary() Complete analysis summary

Example:

```python
from pyputil.core.sca import parse_object
from typing import List, Optional

class DataProcessor:
    """Process data with various methods."""
    
    DEFAULT_VALUE: int = 100
    __slots__ = ('name', '_data')
    
    def __init__(self, name: str):
        self.name = name
        self._data = []
    
    @property
    def count(self) -> int:
        return len(self._data)
    
    @staticmethod
    def validate(value: int) -> bool:
        return value > 0
    
    @classmethod
    def create_default(cls) -> 'DataProcessor':
        return cls("default")
    
    def add(self, value: int) -> None:
        if self.validate(value):
            self._data.append(value)
    
    def _internal_helper(self) -> None:
        pass

obj = DataProcessor("test")
parser = parse_object(obj)

print(f"Type: {parser.type_name}")
print(f"Methods: {parser.methods()}")        # ['add']
print(f"Properties: {parser.properties()}")  # ['count']
print(f"Static methods: {parser.staticmethods()}")  # ['validate']
print(f"Class methods: {parser.classmethods()}")   # ['create_default']
print(f"Private: {parser.private()}")        # ['_data', '_internal_helper']
print(f"Slots: {parser.slots()}")            # ['name', '_data']
print(f"Annotations: {parser.annotations()}")  # {'DEFAULT_VALUE': <class 'int'>}
print(f"Inheritance: {parser.inheritance()}")  # ['DataProcessor', 'object']

# Get method source
body = parser.body("add")
if body:
    print(body)

# Get method signature
sig = parser.signature("add")
print(sig)  # '(self, value: int) -> None'

# Complete summary
summary = parser.summary()
print(f"Total attributes: {summary['attributes_total']}")
print(f"Methods: {len(summary['methods'])}")
```

Code Quality Metrics

Complexity Levels

Score Level Description
1-5 LOW Simple, low risk
6-10 MEDIUM Moderate complexity
11-20 HIGH Complex, consider refactoring
21-50 VERY_HIGH Highly complex, difficult to test
51+ EXTREME Critical, requires immediate action

Maintainability Index

Score Interpretation
85-100 Highly maintainable
65-85 Moderately maintainable
40-65 Needs improvement
0-40 Difficult to maintain

Security Severity Levels

Level Description
INFO Informational, no action required
LOW Minor issue, low priority
MEDIUM Moderate issue, address normally
HIGH Significant issue, prioritize
CRITICAL Critical issue, immediate attention
BLOCKER Blocker, prevents production readiness

Error Handling

```python
from pyputil.core.sca import Source
from pyputil.core.sca._source_parser import SourceNotFoundError, UnsupportedObjectError

try:
    parser = Source("invalid syntax here", parser="code.parser")
except ValueError as e:
    print(f"Syntax error: {e}")

try:
    parser = Source(42, parser="source.parser")
except TypeError as e:
    print(f"Type error: {e}")

try:
    parser = Source("/nonexistent/file.py", target="file")
except FileNotFoundError as e:
    print(f"File not found: {e}")
```

Requirements

· Python 3.8+
· Standard library only for core functionality
· No external dependencies

Key Features Summary

Feature StringParser CodeParser SourceParser ObjectParser
Source code analysis ✓ ✓ ✓ ✗
Bytecode inspection ✗ ✓ ✗ ✗
File operations ✗ ✗ ✓ ✗
Live object inspection ✗ ✗ ✗ ✓
Complexity metrics ✓ ✓ ✓ ✗
Security scanning ✓ ✗ ✗ ✗
Dependency analysis ✓ ✓ ✗ ✗
Type hints extraction ✓ ✓ ✓ ✓
Docstring extraction ✓ ✓ ✓ ✓
Source code extraction ✗ ✗ ✓ ✓
Control flow analysis ✗ ✓ ✗ ✗
Exception analysis ✗ ✓ ✗ ✗
JSON export ✓ ✗ ✗ ✓
Code minification ✗ ✗ ✓ ✗