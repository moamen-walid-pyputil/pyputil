# ZipModule Documentation

## Overview

ZipModule is a comprehensive utility class for compressing, decompressing, and managing Python modules and packages in various archive formats (ZIP, TAR, TAR.GZ, TAR.BZ2, TAR.XZ). It provides intelligent format detection, integrity validation, and detailed metadata extraction.

## Installation

```python
from pyputil.core.zipmodule import ZipModule
```

Core Class: ZipModule

The main class for module compression and archive management.

Constructor:

```python
ZipModule(
    module_name: str,
    *,
    error: bool = True,
    strict: bool = True,
    config: Optional[dict] = None
)
```

Parameters:

Parameter Type Default Description
module_name str Required Python module/package name or archive file path
error bool True If True, raises exceptions on errors
strict bool True If True, requires module to be importable
config dict None Configuration options (see below)

Configuration Options:

Key Type Default Description
output_dir str/Path ./archives Directory for compressed files
overwrite bool False Overwrite existing archives
preserve_structure bool True Keep directory structure in archives
compression_level int 6 Compression level (1-9)
include_hidden bool False Include hidden files/directories
create_checksum bool True Generate SHA256 checksum

Compression Modes

Mode Format Description
zip:def ZIP Standard DEFLATE compression (default)
zip:lzma ZIP LZMA compression (better ratio, slower)
zip:bz2 ZIP BZIP2 compression
zip:std ZIP No compression (store only)
tar TAR No compression (archive only)
tar:gz TAR.GZ GZIP compression
tar:bz2 TAR.BZ2 BZIP2 compression
tar:xz TAR.XZ XZ compression (best ratio)

Usage Examples

Basic Module Compression

```python
from pyputil.core.zipmodule import ZipModule

# Compress a Python module
zm = ZipModule("requests")
archive = zm.zipmodule()  # Creates: ./archives/requests.zip
print(f"Archive created: {archive}")

# Compress with specific format
archive = zm.zipmodule("tar:gz")  # Creates: ./archives/requests.tar.gz
```

Compressing Local Package

```python
# Compress a local package directory
zm = ZipModule("./my_package")
archive = zm.zipmodule("zip:lzma")  # High compression
```

Decompression

```python
# Decompress an archive
zm = ZipModule("my_package.zip")
extracted = zm.unzipmodule()  # Extracts to: ./extracted/my_package/

# Extract to specific directory
extracted = zm.unzipmodule("./output/")
```

Archive Statistics

```python
zm = ZipModule("numpy.zip")
stats = zm.stats()

print(f"Name: {stats['name']}")
print(f"Size: {stats['size']:,} bytes")
print(f"Compression: {stats['compression_type']}")
print(f"Files: {len(stats['contents'])}")
print(f"Checksum: {stats['checksum'][:16]}...")
```

Listing Archive Contents

```python
zm = ZipModule("package.zip")

# Basic listing
for item in zm.list_contents():
    print(item['name'])

# Detailed listing
for item in zm.list_contents(detailed=True):
    print(f"{item['name']}: {item['size']} bytes")
    if 'compression_ratio' in item:
        ratio = item['compression_ratio']
        print(f"  Compression ratio: {ratio:.1%}")
```

Validation and Integrity Checking

```python
zm = ZipModule("important_package.zip")
validation = zm.validate()

if validation['valid']:
    print("Archive is valid and intact")
else:
    print(f"Errors: {validation['errors']}")
    print(f"Warnings: {validation['warnings']}")

if validation['checksum_valid'] is not None:
    print(f"Checksum valid: {validation['checksum_valid']}")
```

Custom Configuration

```python
# Custom configuration
config = {
    "output_dir": "/backups",
    "overwrite": True,
    "preserve_structure": False,  # Flatten structure
    "compression_level": 9,       # Maximum compression
    "include_hidden": True,       # Include .git, .env, etc.
    "create_checksum": True,
}

zm = ZipModule("my_package", config=config, strict=False)
archive = zm.zipmodule("tar:xz")  # Best compression
```

Working with Existing Archives

```python
# Load and analyze existing archive
zm = ZipModule("./backups/old_release.zip")

# Get archive information
stats = zm.stats()
print(f"Archive size: {stats['size']:,} bytes")
print(f"Created: {stats['created']}")
print(f"Modified: {stats['modified']}")

# Validate integrity
if zm.validate()['valid']:
    print("Archive is healthy")

# Extract contents
zm.unzipmodule("./restored/")
```

Error Handling

```python
from pyputil.core.zipmodule import ZipModule

try:
    zm = ZipModule("nonexistent_module", strict=True)
    archive = zm.zipmodule()
except ImportError as e:
    print(f"Module not found: {e}")
except FileNotFoundError as e:
    print(f"File not found: {e}")
except ValueError as e:
    print(f"Invalid compression mode: {e}")
except RuntimeError as e:
    print(f"Compression failed: {e}")
```

Context Manager Usage

```python
with ZipModule("my_package") as zm:
    archive = zm.zipmodule("zip:lzma")
    stats = zm.stats()
    print(f"Created: {archive}")
    print(f"Size: {stats['size']} bytes")
# Resources cleaned up automatically
```

Method Reference

Method Description
zipmodule(zipmode) Compress module/package into archive
unzipmodule(extract_to, mode) Decompress archive to directory
stats() Return comprehensive metadata
validate() Validate archive integrity
list_contents(detailed) List archive contents

Return Values

stats() Return Dictionary

Key Description
name Module/archive name
type 'module' or 'archive'
path Path to module
archive_path Path to archive file
size Size in bytes
contents List of files in archive
checksum SHA256 checksum
compression_type Compression format
created Creation timestamp
modified Last modification time
is_archive Boolean flag
exists Whether archive exists
config Configuration snapshot

validate() Return Dictionary

Key Description
valid Overall validation result
errors List of validation errors
warnings List of warnings
checksum_valid Checksum verification result
structure_valid Structure validation result

Requirements

· Python 3.7+
· Standard library only (zipfile, tarfile, hashlib, pathlib, shutil)
· No external dependencies

Key Features Summary

Feature Description
Multiple formats ZIP, TAR, TAR.GZ, TAR.BZ2, TAR.XZ
Auto-detection Automatic format detection on load
Integrity validation Checksum and archive structure verification
Metadata extraction Size, contents, timestamps, compression info
Flexible configuration Output directory, overwrite, compression level
Error handling Configurable strict/error modes
Context manager Automatic resource cleanup
Path resolution Handles both modules and file paths
Flat structure Option to flatten directory hierarchy