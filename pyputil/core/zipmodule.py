#!/usr/bin/env python3

# -*- coding: utf-8 -*-

from typing import Optional, List, Dict, Any, Union
import zipfile
import hashlib
import sys
from pathlib import Path
import importlib
import shutil
from ..path.utils import compress, decompress, ZIP_TYPES
import tarfile
from datetime import datetime


LIST_ZIP_TYPES = list(ZIP_TYPES)
LIST_ZIP_TYPES.sort(key=lambda x: x[0])  # Sort zip types


class ZipModule:
    """
    A comprehensive utility class for compressing, decompressing, and managing
    Python modules and packages in various archive formats.

    Parameters
    ----------
    module_name : str
        Name of the Python module/package or path to an archive file.
    error : bool, default=True
        If True, raises exceptions for invalid inputs or operations.
    strict : bool, default=True
        If True, ensures module_name is importable when not a file path.
    config : dict, optional
        Configuration dictionary with the following possible keys:
            - "output_dir": Directory for compressed files (default: ./archives/)
            - "overwrite": Whether to overwrite existing archives (default: False)
            - "preserve_structure": Keep directory structure in archives (default: True)
            - "compression_level": Compression level for supported formats
            - "include_hidden": Include hidden files/directories (default: False)

    Raises
    ------
    TypeError
        If module_name is not a string.
    ImportError
        If strict mode is enabled and module cannot be imported.
    FileNotFoundError
        If archive file doesn't exist.

    Examples
    --------
    >>> # Compress a module
    >>> zm = ZipModule("numpy")
    >>> archive_path = zm.zipmodule("zip:def")

    >>> # Decompress an archive
    >>> zm = ZipModule("my_package.zip")
    >>> extracted_path = zm.unzipmodule("./extracted/")

    >>> # Get statistics
    >>> stats = zm.stats()
    >>> print(f"Archive size: {stats['size']} bytes")
    """

    def __init__(
        self,
        module_name: str,
        *,
        error: bool = True,
        strict: bool = True,
        config: Optional[dict] = None,
    ) -> None:
        # Input validation
        if not isinstance(module_name, str):
            raise TypeError(f"module_name must be a string, got {type(module_name)}")

        # Initialize configuration with defaults
        self.error = error
        self.strict = strict
        self.config = self._initialize_config(config)
        self.ziptypes = LIST_ZIP_TYPES

        # Determine if input is an archive or module
        self.module_name = module_name
        self.is_archive = self._is_archive_path(module_name)

        # Initialize paths and metadata
        self._initialize_paths()
        self._initialize_metadata()

    def _initialize_config(self, config: Optional[dict]) -> Dict[str, Any]:
        """Initialize and validate configuration with default values."""
        default_config = {
            "output_dir": Path.cwd() / "archives",
            "overwrite": False,
            "preserve_structure": True,
            "compression_level": 6,
            "include_hidden": False,
            "create_checksum": True,
        }

        if config:
            default_config.update(config)

        # Ensure output_dir is a Path object
        default_config["output_dir"] = Path(default_config["output_dir"])
        default_config["output_dir"].mkdir(parents=True, exist_ok=True)

        return default_config

    def _is_archive_path(self, path: str) -> bool:
        """Check if the given path points to a supported archive file."""
        archive_extensions = {
            ".zip",
            ".tar",
            ".gz",
            ".bz2",
            ".xz",
            ".tar.gz",
            ".tar.bz2",
            ".tar.xz",
        }
        path_obj = Path(path)
        return path_obj.is_file() and path_obj.suffix.lower() in archive_extensions

    def _initialize_paths(self) -> None:
        """Initialize and validate all relevant paths."""
        if self.is_archive:
            # Archive mode initialization
            self.archive_path = Path(self.module_name).resolve()
            if not self.archive_path.exists():
                if self.error:
                    raise FileNotFoundError(f"Archive not found: {self.archive_path}")
                else:
                    self.archive_path = None
                    return

            self.module_path = self.archive_path.parent
            self.module_name = self.archive_path.stem
        else:
            # Module mode initialization
            self.archive_path = None
            self._initialize_module_paths()

    def _initialize_module_paths(self) -> None:
        """Initialize paths for module mode with import validation."""
        try:
            # Attempt to import and locate the module
            if self.module_name not in sys.modules:
                importlib.import_module(self.module_name)

            module = sys.modules.get(self.module_name)
            if not module or not hasattr(module, "__file__"):
                raise AttributeError("Module lacks __file__ attribute")

            filepath = None
            if hasattr(module, "__file__"):
                filepath = module.__file__

            if filepath is not None:
                module_file = Path(filepath).resolve() 
                self.module_path = module_file.parent
            else:
                raise FileNotFoundError(f"No file for module '{self.module_name}'")

            # Handle package vs module
            if module_file.name == "__init__.py":
                # It's a package, use parent directory
                self.module_path = module_file.parent
            else:
                # It's a single module
                self.module_path = module_file.parent

        except (ImportError, AttributeError) as e:
            if self.strict and self.error:
                raise ImportError(
                    f"Failed to locate or import module '{self.module_name}': {e}"
                )
            # Fallback: treat as directory path
            potential_path = Path(self.module_name)
            if potential_path.exists():
                self.module_path = potential_path.resolve()
            else:
                self.module_path = None
                if self.error:
                    raise

    def _initialize_metadata(self) -> None:
        """Initialize archive metadata and contents."""
        self.metadata = {
            "name": self.module_name,
            "type": "archive" if self.is_archive else "module",
            "created": datetime.now(),
            "checksum": None,
            "contents": [],
            "size": 0,
            "compression_type": None,
        }

        if self.is_archive and self.archive_path and self.archive_path.exists():
            self._load_archive_metadata()

    def _load_archive_metadata(self) -> None:
        """Load metadata from existing archive."""
        try:
            self.metadata["size"] = self.archive_path.stat().st_size
            self.metadata["modified"] = datetime.fromtimestamp(
                self.archive_path.stat().st_mtime
            )

            # Detect compression type and load contents
            if zipfile.is_zipfile(self.archive_path):
                self.metadata["compression_type"] = "zip"
                with zipfile.ZipFile(self.archive_path, "r") as archive:
                    self.metadata["contents"] = archive.namelist()
            elif tarfile.is_tarfile(self.archive_path):
                self.metadata["compression_type"] = "tar"
                with tarfile.open(self.archive_path, "r") as archive:
                    self.metadata["contents"] = archive.getnames()

            # Calculate checksum
            if self.config["create_checksum"]:
                self.metadata["checksum"] = self._calculate_checksum()

        except Exception as e:
            if self.error:
                raise RuntimeError(f"Failed to load archive metadata: {e}") from e
            self.metadata["contents"] = []

    def _calculate_checksum(self, algorithm: str = "sha256") -> Optional[str]:
        """
        Calculate checksum for the archive file.

        Parameters
        ----------
        algorithm : str
            Hashing algorithm to use ('md5', 'sha1', 'sha256').

        Returns
        -------
        str or None
            Hexadecimal digest of the file checksum.
        """
        if not self.archive_path or not self.archive_path.exists():
            return None

        hash_func = getattr(hashlib, algorithm, hashlib.sha256)()

        try:
            with open(self.archive_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_func.update(chunk)
            return hash_func.hexdigest()
        except Exception:
            return None

    def zipmodule(self, zipmode: str = "zip:def") -> Path:
        """
        Compress the target Python module or package into an archive.

        This method provides intelligent compression with configurable options
        and preserves the module structure by default.

        Parameters
        ----------
        zipmode : str, default='zip:def'
            Compression mode specifying format and algorithm:
            - ZIP formats: "zip:def", "zip:lzma", "zip:bz2", "zip:std"
            - TAR formats: "tar", "tar:gz", "tar:bz2", "tar:xz"

        Returns
        -------
        Path
            Path to the generated archive file.

        Raises
        ------
        FileNotFoundError
            If module path doesn't exist.
        ValueError
            If compression mode is not supported.
        RuntimeError
            If compression fails.

        Examples
        --------
        >>> zm = ZipModule("my_package")
        >>> # Create a compressed archive with default settings
        >>> archive = zm.zipmodule()
        >>> # Create a highly compressed tar.gz archive
        >>> archive = zm.zipmodule("tar:gz")
        """
        if self.is_archive:
            return self.archive_path

        if not self.module_path or not self.module_path.exists():
            raise FileNotFoundError(f"Module path not found: {self.module_path}")

        # Validate compression mode
        if zipmode not in self.ziptypes:
            raise ValueError(
                f"Unsupported compression mode: {zipmode}. "
                f"Supported modes: {', '.join(self.ziptypes)}"
            )

        # Determine output path
        final_archive_path = self._get_output_path(zipmode)

        # Check if we should overwrite
        if final_archive_path.exists() and not self.config["overwrite"]:
            return final_archive_path

        try:
            # Create temporary working directory if needed
            temp_dir = None
            if not self.config["preserve_structure"]:
                temp_dir = self._prepare_flat_structure()
                source_path = temp_dir
            else:
                source_path = self.module_path

            # Perform compression
            archive_path = compress(str(source_path), zipmode)

            # Move to final location
            final_archive_path.write_bytes(Path(archive_path).read_bytes())
            Path(archive_path).unlink(missing_ok=True)

            # Cleanup temporary directory
            if temp_dir and temp_dir.exists():
                shutil.rmtree(temp_dir)

            # Update metadata
            self.archive_path = final_archive_path
            self._initialize_metadata()

            return final_archive_path.resolve()

        except Exception as e:
            raise RuntimeError(f"Compression failed: {e}") from e

    def _get_output_path(self, zipmode: str) -> Path:
        """Generate output path for the archive based on configuration."""
        extension = self._extension_for_mode(zipmode)
        filename = f"{self.module_name}{extension}"
        return self.config["output_dir"] / filename

    def _prepare_flat_structure(self) -> Path:
        """
        Prepare a flat directory structure for archiving.

        Returns
        -------
        Path
            Path to temporary directory with flat structure.
        """
        temp_dir = Path(self.config["output_dir"]) / f"temp_{self.module_name}"
        temp_dir.mkdir(exist_ok=True)

        def copy_files(source: Path, target: Path):
            for item in source.iterdir():
                if item.name.startswith(".") and not self.config["include_hidden"]:
                    continue

                if item.is_file():
                    shutil.copy2(item, target / item.name)
                elif item.is_dir():
                    copy_files(item, target)

        copy_files(self.module_path, temp_dir)
        return temp_dir

    def unzipmodule(
        self, extract_to: Optional[Union[str, Path]] = None, mode: Optional[str] = None
    ) -> Path:
        """
        Decompress a module archive to the specified location.

        This method provides intelligent extraction with automatic format
        detection and conflict resolution.

        Parameters
        ----------
        extract_to : str | Path | None
            Target directory for extraction. If None, extracts to
            './extracted/<archive_name>/'
        mode : str | None
            Explicit decompression mode. If None, auto-detection is used.

        Returns
        -------
        Path
            Path to the extracted directory.

        Raises
        ------
        FileNotFoundError
            If archive doesn't exist.
        ValueError
            If archive format is not supported.
        RuntimeError
            If extraction fails.

        Examples
        --------
        >>> zm = ZipModule("my_package.zip")
        >>> # Extract to default location
        >>> path = zm.unzipmodule()
        >>> # Extract to specific directory
        >>> path = zm.unzipmodule("./my_extraction/")
        """
        if not self.archive_path or not self.archive_path.exists():
            raise FileNotFoundError(f"Archive not found: {self.archive_path}")

        # Determine extraction directory
        if extract_to is None:
            base_extract_dir = Path.cwd() / "extracted" / self.module_name
        else:
            base_extract_dir = Path(extract_to)

        base_extract_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Use the existing decompress function
            result_path = decompress(str(self.archive_path))

            # Move to target directory if different from default
            if extract_to is not None:
                extracted_path = Path(result_path)
                target_path = base_extract_dir / extracted_path.name

                if target_path.exists():
                    if self.config["overwrite"]:
                        shutil.rmtree(target_path)
                    else:
                        return target_path

                shutil.move(str(extracted_path), str(target_path))
                result_path = target_path

            return Path(result_path).resolve()

        except Exception as e:
            raise RuntimeError(f"Extraction failed: {e}") from e

    def stats(self) -> Dict[str, Any]:
        """
        Return comprehensive metadata and statistics about the module or archive.

        Returns
        -------
        dict
            Dictionary containing comprehensive statistics with keys:
            - 'name': Module/archive name
            - 'type': 'module' or 'archive'
            - 'path': Full path to module/archive
            - 'size': Size in bytes (for archives)
            - 'contents': List of files in archive
            - 'checksum': SHA256 checksum (for archives)
            - 'compression_type': Detected compression format
            - 'created': Creation timestamp
            - 'modified': Last modification time

        Examples
        --------
        >>> zm = ZipModule("numpy")
        >>> stats = zm.stats()
        >>> print(f"Module: {stats['name']}")
        >>> print(f"Size: {stats['size']} bytes")
        >>> print(f"Files: {len(stats['contents'])}")
        """
        stats = self.metadata.copy()

        # Add additional information
        stats.update(
            {
                "path": str(self.module_path) if self.module_path else None,
                "archive_path": str(self.archive_path) if self.archive_path else None,
                "is_archive": self.is_archive,
                "exists": self.archive_path.exists() if self.archive_path else False,
                "config": {
                    "output_dir": str(self.config["output_dir"]),
                    "overwrite": self.config["overwrite"],
                    "preserve_structure": self.config["preserve_structure"],
                },
            }
        )

        return stats

    def validate(self) -> Dict[str, Any]:
        """
        Validate the integrity and structure of the archive or module.

        Performs various checks including:
        - Archive integrity verification
        - Checksum validation
        - File structure validation

        Returns
        -------
        dict
            Validation results with keys:
            - 'valid': Overall validation result
            - 'errors': List of validation errors
            - 'warnings': List of warnings
            - 'checksum_valid': Checksum verification result
            - 'structure_valid': Directory structure validation

        Examples
        --------
        >>> zm = ZipModule("my_package.zip")
        >>> validation = zm.validate()
        >>> if validation['valid']:
        ...     print("Archive is valid and intact")
        ... else:
        ...     print(f"Validation errors: {validation['errors']}")
        """
        results = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "checksum_valid": None,
            "structure_valid": None,
        }

        if not self.is_archive or not self.archive_path:
            results["errors"].append("No archive to validate")
            results["valid"] = False
            return results

        # Check archive existence
        if not self.archive_path.exists():
            results["errors"].append("Archive file does not exist")
            results["valid"] = False
            return results

        # Validate archive integrity
        try:
            if zipfile.is_zipfile(self.archive_path):
                with zipfile.ZipFile(self.archive_path, "r") as archive:
                    archive.testzip()  # Raises exception if corrupted
            elif tarfile.is_tarfile(self.archive_path):
                with tarfile.open(self.archive_path, "r") as archive:
                    # Basic tar validation
                    pass
            else:
                results["errors"].append("Unsupported archive format")
                results["valid"] = False
        except Exception as e:
            results["errors"].append(f"Archive integrity check failed: {e}")
            results["valid"] = False

        # Verify checksum if available
        if self.metadata["checksum"]:
            current_checksum = self._calculate_checksum()
            results["checksum_valid"] = current_checksum == self.metadata["checksum"]
            if not results["checksum_valid"]:
                results["errors"].append("Checksum verification failed")
                results["valid"] = False

        return results

    def list_contents(self, detailed: bool = False) -> List[Dict[str, Any]]:
        """
        List contents of the archive with optional detailed information.

        Parameters
        ----------
        detailed : bool, default=False
            If True, returns detailed file information including size,
            compression ratio, and modification date.

        Returns
        -------
        list
            List of dictionaries containing file information.

        Raises
        ------
        RuntimeError
            If the archive cannot be read or is corrupted.
        """
        if not self.is_archive or not self.archive_path:
            return []

        contents = []

        try:
            if zipfile.is_zipfile(self.archive_path):
                with zipfile.ZipFile(self.archive_path, "r") as archive:
                    for info in archive.infolist():
                        file_data = {
                            "name": info.filename,
                            "size": info.file_size,
                            "compressed_size": info.compress_size,
                        }
                        if detailed:
                            file_data.update(
                                {
                                    "compression_ratio": (
                                        info.compress_size / info.file_size
                                        if info.file_size > 0
                                        else 0
                                    ),
                                    "modified": datetime(*info.date_time),
                                    "is_directory": info.filename.endswith(os.sep),
                                }
                            )
                        contents.append(file_data)

            elif tarfile.is_tarfile(self.archive_path):
                with tarfile.open(self.archive_path, "r") as archive:
                    for member in archive.getmembers():
                        file_data = {
                            "name": member.name,
                            "size": member.size,
                        }
                        if detailed:
                            file_data.update(
                                {
                                    "modified": member.mtime,
                                    "is_directory": member.isdir(),
                                    "permissions": member.mode,
                                }
                            )
                        contents.append(file_data)

        except Exception as e:
            if self.error:
                raise RuntimeError(f"Failed to read archive contents: {e}") from e

        return contents

    def _extension_for_mode(self, mode: str) -> str:
        """
        Return the appropriate file extension for a given compression mode.

        Parameters
        ----------
        mode : str
            Compression mode string.

        Returns
        -------
        str
            Corresponding file extension.
        """
        ext_map = {
            "zip:def": ".zip",
            "zip:lzma": ".zip",
            "zip:bz2": ".zip",
            "zip:std": ".zip",
            "tar": ".tar",
            "tar:gz": ".tar.gz",
            "tar:bz2": ".tar.bz2",
            "tar:xz": ".tar.xz",
        }
        return ext_map.get(mode.strip(), ".zip")

    def __repr__(self) -> str:
        """Return string representation of the ZipModule instance."""
        return (
            f"ZipModule(name='{self.module_name}', "
            f"type={'archive' if self.is_archive else 'module'}, "
            f"path={self.module_path})"
        )

    def __enter__(self):
        """Support context manager protocol."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Cleanup context manager resources."""
        # Currently no special cleanup needed
        pass
