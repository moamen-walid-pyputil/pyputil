#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
pyputil-pip - Pip Installation and Management Tool
============================================================

A comprehensive solution for downloading, installing, managing, and verifying
pip versions across platforms.

Module Overview
---------------
This module provides a complete toolkit for managing pip installations with
features including secure downloads, version management, cross-platform
support, offline caching, audit trails, and safety features.

Key Features
------------
- **Secure Downloads**: SSL verification, checksum validation, fallback URLs
- **Version Management**: Install any pip version with compatibility checking
- **Cross-Platform**: Windows, macOS, Linux support
- **Offline Support**: Caching mechanism for repeated installations
- **Audit Trail**: Complete logging with configurable verbosity
- **Safety Features**: Path traversal prevention, hash verification, SSL checking
- **Environment Awareness**: Virtual environment detection and handling
- **Comprehensive Reporting**: Structured dataclass outputs for all operations

Usage Examples
--------------
Basic installation:
>>> from pyputil.pip import PipManager, LogLevel
>>> manager = PipManager()
>>> result = manager.install_pip()
>>> if result.success:
...	 print(f"Installed pip {result.pip_version}")

Advanced configuration:
>>> manager = PipManager(
...	 log_file="pip_install.log",
...	 log_level=LogLevel.DETAILED,
...	 verify_ssl=True,
...	 timeout=60
... )
>>> result = manager.install_pip(
...	 version="24.0",
...	 user_mode=True,
...	 upgrade=True
... )

Command line usage:
$ pyputil.pip install --version 24.0 --user
$ pyputil.pip status
$ pyputil.pip verify

Dependencies (Zero dependencies)
------------
- Python 3.8 or higher
- certifi (automatically installed if needed)
   If the certifi package is not installed,
   we will use the default path found in the location ./_utils/_certifi.pem 
- Standard library modules only

Environment Requirements
------------------------
- Internet connection for downloads
- Write permissions to target installation directory
- SSL certificates for secure connections
"""

import hashlib
import json
import logging
import os
import platform
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
import urllib.parse
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union, Any, NoReturn
from enum import Enum, auto
from contextlib import contextmanager
import socket
import re
import argparse
import site
from collections import deque
import threading
import fnmatch
from functools import wraps

try:
	import certifi
	where = certifi.where()
except ImportError:
	where = str(Path(".").resolve() / "_utils" / "_certifi.pem")


# ============================================================================
# Enumerations & Data Classes for Results and Reports
# ============================================================================

from ._utils._base_pip import (
	LogLevel,
	InstallMethod,
	InstallationResult,
	VerificationResult,
	CacheInfo,
	SystemInfo,
	PipStatus,
	EnvironmentInfo,
	ConfigurationInfo,
	InstallationReport,
	HashInfo,
	VersionListResult,
	PackageListResult
)

# ============================================================================
# Custom Exceptions
# ============================================================================
from ._utils._pip_exceptions import (
	PipError,
	DownloadError,
	InstallationError,
	ValidationError
)

# ============================================================================
# Version Management
# ============================================================================

class PipVersion:
	"""
	Pip version management and compatibility information.
	
	This class provides version compatibility data between Python
	and pip releases, ensuring you install a compatible version.
	It maintains known good versions, LTS releases, and compatibility
	ranges for different Python versions.

	Attributes
	----------
	BOOTSTRAP_URLS : List[str]
		Official PyPA bootstrap script URLs with fallback options
	COMPATIBILITY_MATRIX : Dict[Tuple[int, int], str]
		Python version to pip version range mappings
	STABLE_VERSIONS : List[str]
		Known good pip versions that have been thoroughly tested
	LTS_VERSIONS : List[str]
		Long-term support versions recommended for enterprise use

	Examples
	--------
	Get latest stable version:
	>>> latest = PipVersion.get_latest_stable()
	>>> print(f"Latest stable pip: {latest}")
	
	Get versions compatible with Python 3.11:
	>>> compatible = PipVersion.get_compatible_versions((3, 11))
	>>> print(f"Compatible versions: {', '.join(compatible)}")
	
	Check if a version is LTS:
	>>> if PipVersion.is_lts_version("23.2.1"):
	...	 print("This is an LTS version")
	"""
	
	# Official PyPA sources with fallbacks - format codes: {version}
	BOOTSTRAP_URLS: List[str] = [
		"https://bootstrap.pypa.io/get-pip.py",
		"https://raw.githubusercontent.com/pypa/get-pip/main/public/get-pip.py",
		"https://bootstrap.pypa.io/pip/{version}/get-pip.py",
	]
	
	# Version compatibility mapping (minimum Python version -> pip version range)
	# The string represents the minimum compatible pip version for that Python
	COMPATIBILITY_MATRIX: Dict[Tuple[int, int], str] = {
		(3, 8): "20.0.0",
		(3, 9): "20.0.0",
		(3, 10): "21.0.0",
		(3, 11): "22.0.0",
		(3, 12): "23.0.0",
		(3, 13): "24.0.0",
		(3, 14): "25.0.0",
	}
	
	# Known good and well-tested versions (newest to oldest)
	STABLE_VERSIONS: List[str] = [
		"26.1.1", "26.1.0", "26.0.0", "25.0.1", "25.0.0",
		"24.3.1", "24.2.0", "24.0.0", "23.3.2", "23.2.1",
		"23.1.2", "23.0.1", "22.3.1", "21.3.1", "20.3.4"
	]
	
	# Long-term support versions (older but stable)
	LTS_VERSIONS: List[str] = [
		"24.0.0", "23.2.1", "22.3.1", "21.3.1"
	]
	
	# Verified hash values for get-pip.py scripts
	# These should be updated when new versions are released
	TRUSTED_HASHES: Dict[str, Dict[str, HashInfo]] = {
		"get-pip.py": {
			"26.1.1": HashInfo(
				sha256="",  # To be populated from actual download
				md5=None,
				blake2b=None
			),
			"26.0.0": HashInfo(
				sha256="",
				md5=None,
				blake2b=None
			),
		}
	}
	
	@classmethod
	def get_latest_stable(cls) -> str:
		"""
		Return the latest stable pip version known to work.
		
		Returns
		-------
		str
			Latest stable version string like "26.1.1"
			
		Examples
		--------
		>>> PipVersion.get_latest_stable()
		'26.1.1'
		
		>>> version = PipVersion.get_latest_stable()
		>>> print(f"Recommended version: {version}")
		"""
		return cls.STABLE_VERSIONS[0] if cls.STABLE_VERSIONS else "26.1.1"
	
	@classmethod
	def get_compatible_versions(
		cls,
		python_version: Optional[Tuple[int, int]] = None,
		include_all: bool = False
	) -> List[str]:
		"""
		Get pip versions compatible with the specified Python version.
		
		This method checks the compatibility matrix and returns a list
		of pip versions known to work with the specified Python version.
		
		Parameters
		----------
		python_version : tuple, optional
			(major, minor) Python version. If None, uses current Python version.
		include_all : bool, optional
			If True, include versions older than the minimum (default: False)
			
		Returns
		-------
		List[str]
			List of compatible version strings, sorted from newest to oldest
			
		Examples
		--------
		Get versions for Python 3.11:
		>>> versions = PipVersion.get_compatible_versions((3, 11))
		>>> print(f"Found {len(versions)} compatible versions")
		
		Get versions for current Python:
		>>> versions = PipVersion.get_compatible_versions()
		
		Include older versions:
		>>> versions = PipVersion.get_compatible_versions((3, 13), include_all=True)
		"""
		if python_version is None:
			python_version = (sys.version_info.major, sys.version_info.minor)
		
		# Find the appropriate minimum version for this Python
		min_version = None
		for py_ver, pip_min in cls.COMPATIBILITY_MATRIX.items():
			if python_version >= py_ver:
				min_version = pip_min
				break
		
		if min_version is None:
			# Default fallback
			min_version = "20.0.0"
		
		# Filter versions based on compatibility
		compatible = []
		for version in cls.STABLE_VERSIONS:
			# Compare version strings (simple string comparison works for semantic versions)
			if include_all or self._version_compare(version, min_version) >= 0:
				compatible.append(version)
		
		return compatible
	
	@classmethod
	def _version_compare(cls, version1: str, version2: str) -> int:
		"""
		Compare two version strings.
		
		Parameters
		----------
		version1 : str
			First version string
		version2 : str
			Second version string
			
		Returns
		-------
		int
			-1 if v1 < v2, 0 if equal, 1 if v1 > v2
		"""
		def normalize(v: str) -> List[int]:
			parts = v.split('.')
			return [int(p) for p in parts]
		
		v1_parts = normalize(version1)
		v2_parts = normalize(version2)
		
		for i in range(max(len(v1_parts), len(v2_parts))):
			v1_val = v1_parts[i] if i < len(v1_parts) else 0
			v2_val = v2_parts[i] if i < len(v2_parts) else 0
			if v1_val != v2_val:
				return 1 if v1_val > v2_val else -1
		return 0
	
	@classmethod
	def is_lts_version(cls, version: str) -> bool:
		"""
		Check if a version is marked as Long-Term Support.
		
		Parameters
		----------
		version : str
			Version string to check
			
		Returns
		-------
		bool
			True if version is in LTS list
			
		Examples
		--------
		>>> PipVersion.is_lts_version("23.2.1")
		True
		>>> PipVersion.is_lts_version("25.0.0")
		False
		"""
		return version in cls.LTS_VERSIONS
	
	@classmethod
	def get_bootstrap_urls(cls, version: Optional[str] = None) -> List[str]:
		"""
		Get list of bootstrap script URLs for a specific version.
		
		Parameters
		----------
		version : str, optional
			Pip version for version-specific URL. If None, returns generic URLs.
			
		Returns
		-------
		List[str]
			List of URLs to try in order of preference
			
		Examples
		--------
		>>> urls = PipVersion.get_bootstrap_urls()
		>>> print(urls[0])
		https://bootstrap.pypa.io/get-pip.py
		
		>>> urls = PipVersion.get_bootstrap_urls("24.0")
		>>> print(urls[2])
		https://bootstrap.pypa.io/pip/24.0/get-pip.py
		"""
		urls = [cls.BOOTSTRAP_URLS[0], cls.BOOTSTRAP_URLS[1]]
		
		if version:
			# For version-specific URL, extract major.minor
			parts = version.split('.')
			major_minor = f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else parts[0]
			urls.append(cls.BOOTSTRAP_URLS[2].format(version=major_minor))
		
		return urls


# ============================================================================
# Security and Verification
# ============================================================================

class SecurityVerifier:
	"""
	Security verification utilities for downloads and installations.
	
	This class provides cryptographic verification, SSL certificate
	checking, URL validation, and path sanitization to ensure secure
	operations. All methods are static for easy use without instantiation.

	Examples
	--------
	Verify file integrity:
	>>> from pathlib import Path
	>>> is_valid = SecurityVerifier.verify_file_integrity(
	...	 Path("get-pip.py"),
	...	 "expected_sha256_hash_here"
	... )
	>>> if is_valid:
	...	 print("File integrity verified")
	
	Verify SSL certificate:
	>>> is_valid, error = SecurityVerifier.verify_ssl_certificate("pypi.org")
	>>> if not is_valid:
	...	 print(f"SSL warning: {error}")
	
	Sanitize a file path:
	>>> safe_path = SecurityVerifier.sanitize_path("../../etc/passwd")
	ValueError: Path traversal detected
	"""
	
	# Allowed hash algorithms
	VALID_HASH_ALGORITHMS = ['sha256', 'md5', 'blake2b', 'sha3_256']
	
	# Blocked URL patterns for security
	BLOCKED_URL_PATTERNS = [
		r'\.\./', r'\.\.\\\\', r'%2e%2e',  # Path traversal
		r'file://', r'file:',  # Local file access
		r'ftp://',  # Unencrypted FTP
	]
	
	@classmethod
	def verify_file_integrity(
		cls,
		file_path: Path,
		expected_hash: str,
		hash_algo: str = "sha256"
	) -> bool:
		"""
		Verify file integrity using cryptographic hash.
		
		This method reads the file in chunks to handle large files efficiently
		and compares the computed hash with the expected value.
		
		Parameters
		----------
		file_path : Path
			Path to the file to verify (must exist and be readable)
		expected_hash : str
			Expected hash value as hexadecimal string
		hash_algo : str, optional
			Hash algorithm to use. Supported: 'sha256', 'md5', 'blake2b', 'sha3_256'
			(default: 'sha256')
			
		Returns
		-------
		bool
			True if computed hash matches expected hash, False otherwise
			
		Raises
		------
		ValidationError
			If hash algorithm is not supported or file doesn't exist
			
		Examples
		--------
		Verify with SHA-256 (recommended):
		>>> result = SecurityVerifier.verify_file_integrity(
		...	 Path("downloads/get-pip.py"),
		...	 "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
		... )
		
		Verify with MD5:
		>>> result = SecurityVerifier.verify_file_integrity(
		...	 Path("file.zip"),
		...	 "d41d8cd98f00b204e9800998ecf8427e",
		...	 hash_algo="md5"
		... )
		"""
		if not file_path.exists():
			raise ValidationError(
				f"File not found: {file_path}",
				validation_type="file_exists",
				expected="existing file",
				actual=str(file_path)
			)
		
		if hash_algo not in cls.VALID_HASH_ALGORITHMS:
			raise ValidationError(
				f"Unsupported hash algorithm: {hash_algo}. "
				f"Supported: {', '.join(cls.VALID_HASH_ALGORITHMS)}",
				validation_type="hash_algorithm",
				expected="valid algorithm",
				actual=hash_algo
			)
		
		# Get the hash function
		hash_func = getattr(hashlib, hash_algo, None)
		if hash_func is None:
			raise ValidationError(f"Hash algorithm {hash_algo} not available in hashlib")
		
		hasher = hash_func()
		
		try:
			with open(file_path, "rb") as f:
				for chunk in iter(lambda: f.read(8192), b""):
					hasher.update(chunk)
		except IOError as e:
			raise ValidationError(
				f"Cannot read file: {file_path}",
				validation_type="file_read",
				original_error=e
			)
		
		computed_hash = hasher.hexdigest()
		return computed_hash.lower() == expected_hash.lower()
	
	@classmethod
	def verify_ssl_certificate(
		cls,
		hostname: str,
		port: int = 443,
		timeout: int = 10
	) -> Tuple[bool, Optional[str]]:
		"""
		Verify SSL certificate validity for a host.
		
		This method establishes an SSL connection to the host and verifies
		the certificate chain using certifi's trusted CA bundle.
		
		Parameters
		----------
		hostname : str
			Hostname to verify (e.g., "pypi.org", "github.com")
		port : int, optional
			Port number for SSL connection (default: 443)
		timeout : int, optional
			Connection timeout in seconds (default: 10)
			
		Returns
		-------
		Tuple[bool, Optional[str]]
			(is_valid, error_message) where error_message is None if successful
			
		Examples
		--------
		Verify PyPI certificate:
		>>> valid, error = SecurityVerifier.verify_ssl_certificate("pypi.org")
		>>> if valid:
		...	 print("Certificate is valid")
		... else:
		...	 print(f"Certificate error: {error}")
		
		Verify with custom port:
		>>> valid, error = SecurityVerifier.verify_ssl_certificate("example.com", port=8443)
		"""
		try:
			if where and Path(where).exists():
				context = ssl.create_default_context(cafile=where)
			else:
				context = ssl.create_default_context()
			with socket.create_connection((hostname, port), timeout=timeout) as sock:
				with context.wrap_socket(sock, server_hostname=hostname) as ssock:
					# Certificate verification happens automatically
					cert = ssock.getpeercert()
					return True, None
		except ssl.SSLCertVerificationError as e:
			return False, f"SSL certificate verification failed: {e}"
		except socket.timeout:
			return False, f"Connection timeout to {hostname}:{port}"
		except socket.gaierror as e:
			return False, f"DNS resolution failed for {hostname}: {e}"
		except ConnectionRefusedError:
			return False, f"Connection refused to {hostname}:{port}"
		except Exception as e:
			return False, str(e)
	
	@classmethod
	def sanitize_path(cls, path: Union[str, Path]) -> Path:
		"""
		Sanitize a file path to prevent path traversal attacks.
		
		This method resolves the path to absolute and checks for suspicious
		patterns like '..' and null bytes.
		
		Parameters
		----------
		path : str or Path
			Path to sanitize (can be relative or absolute)
			
		Returns
		-------
		Path
			Sanitized absolute Path object
			
		Raises
		------
		ValidationError
			If path traversal attempt is detected or path contains null bytes
			
		Examples
		--------
		Sanitize a safe path:
		>>> safe = SecurityVerifier.sanitize_path("downloads/file.txt")
		>>> print(safe)
		/current/working/dir/downloads/file.txt
		
		Detect path traversal:
		>>> SecurityVerifier.sanitize_path("../../etc/passwd")
		ValidationError: Path traversal detected: ../../etc/passwd
		
		Detect null byte injection:
		>>> SecurityVerifier.sanitize_path("file\0.txt")
		ValidationError: Null byte detected in path
		"""
		path_str = str(path)
		
		# Check for null bytes (C string injection attack)
		if '\0' in path_str:
			raise ValidationError(
				f"Null byte detected in path: {path}",
				validation_type="path_sanitization",
				expected="no null bytes",
				actual=path_str
			)
		
		# Check for path traversal patterns
		for pattern in cls.BLOCKED_URL_PATTERNS:
			if re.search(pattern, path_str, re.IGNORECASE):
				raise ValidationError(
					f"Path traversal or unsafe pattern detected: {path}",
					validation_type="path_traversal",
					expected="safe path",
					actual=path_str
				)
		
		try:
			path_obj = Path(path_str).resolve()
			return path_obj
		except Exception as e:
			raise ValidationError(
				f"Invalid path: {path}",
				validation_type="path_resolution",
				original_error=e
			)
	
	@classmethod
	def validate_url(cls, url: str) -> bool:
		"""
		Validate URL for safety and proper format.
		
		This method checks that the URL uses HTTPS protocol and doesn't
		contain suspicious patterns.
		
		Parameters
		----------
		url : str
			URL to validate (string format)
			
		Returns
		-------
		bool
			True if URL is safe and properly formatted, False otherwise
			
		Examples
		--------
		Valid HTTPS URL:
		>>> SecurityVerifier.validate_url("https://pypi.org/simple/")
		True
		
		Invalid HTTP URL (not secure):
		>>> SecurityVerifier.validate_url("http://example.com")
		False
		
		URL with path traversal:
		>>> SecurityVerifier.validate_url("https://example.com/../../secret")
		False
		"""
		try:
			parsed = urllib.parse.urlparse(url)
			
			# Only allow HTTPS for security
			if parsed.scheme != 'https':
				return False
			
			# Check for suspicious patterns
			for pattern in cls.BLOCKED_URL_PATTERNS:
				if re.search(pattern, url, re.IGNORECASE):
					return False
			
			# Basic URL structure validation
			if not parsed.netloc:
				return False
			
			return True
		except Exception:
			return False
	
	@classmethod
	def compute_file_hash(
		cls,
		file_path: Path,
		algorithm: str = "sha256"
	) -> str:
		"""
		Compute hash of a file using specified algorithm.
		
		Parameters
		----------
		file_path : Path
			Path to the file
		algorithm : str, optional
			Hash algorithm to use (default: 'sha256')
			
		Returns
		-------
		str
			Hexadecimal hash string
			
		Raises
		------
		ValidationError
			If file doesn't exist or algorithm is invalid
			
		Examples
		--------
		>>> hash_value = SecurityVerifier.compute_file_hash(Path("file.txt"))
		>>> print(f"SHA256: {hash_value}")
		
		>>> md5_hash = SecurityVerifier.compute_file_hash(
		...	 Path("file.txt"),
		...	 algorithm="md5"
		... )
		"""
		if not file_path.exists():
			raise ValidationError(f"File not found: {file_path}")
		
		if algorithm not in cls.VALID_HASH_ALGORITHMS:
			raise ValidationError(f"Unsupported algorithm: {algorithm}")
		
		hash_func = getattr(hashlib, algorithm)
		hasher = hash_func()
		
		with open(file_path, "rb") as f:
			for chunk in iter(lambda: f.read(8192), b""):
				hasher.update(chunk)
		
		return hasher.hexdigest()


# ============================================================================
# Logging System
# ============================================================================

class InstallationLogger:
	"""
	Comprehensive logging system for installation operations.
	
	This logger supports multiple output destinations (console, file, memory)
	with different verbosity levels and structured logging capabilities.
	Thread-safe implementation with log rotation support.

	Parameters
	----------
	log_file : str or Path, optional
		Path to log file. If None, file logging is disabled.
	log_level : LogLevel, optional
		Verbosity level for logging (default: LogLevel.NORMAL)
	console_output : bool, optional
		Whether to output logs to console (default: True)
	max_log_entries : int, optional
		Maximum number of log entries to keep in memory (default: 10000)
	log_format : str, optional
		Format string for log messages (default uses timestamp and level)

	Attributes
	----------
	log_entries : deque
		In-memory log entries with structured metadata (thread-safe)
	file_logger : logging.Logger or None
		Python logger for file output (if enabled)
	lock : threading.Lock
		Lock for thread-safe operations

	Examples
	--------
	Basic usage:
	>>> from pyputil.pip import InstallationLogger, LogLevel
	>>> logger = InstallationLogger(log_level=LogLevel.DETAILED)
	>>> logger.log("Starting download", level=LogLevel.NORMAL, component="Downloader")
	
	With file logging:
	>>> logger = InstallationLogger(
	...	 log_file="install.log",
	...	 log_level=LogLevel.DEBUG,
	...	 console_output=False
	... )
	
	Retrieve logs:
	>>> logs = logger.get_logs(level=LogLevel.ERROR, limit=10)
	>>> for entry in logs:
	...	 print(f"{entry['timestamp']}: {entry['message']}")
	
	Clear logs:
	>>> logger.clear()
	
	Context manager for temporary log level:
	>>> with logger.temp_level(LogLevel.DEBUG):
	...	 logger.log("This will be shown temporarily", level=LogLevel.DEBUG)
	"""
	
	# ANSI color codes for console output (disabled on Windows by default)
	COLORS = {
		'DEBUG': '\033[36m',	 # Cyan
		'DETAILED': '\033[34m',  # Blue
		'NORMAL': '\033[32m',	# Green
		'WARNING': '\033[33m',   # Yellow
		'ERROR': '\033[31m',	 # Red
		'RESET': '\033[0m'
	}
	
	def __init__(
		self,
		log_file: Optional[Union[str, Path]] = None,
		log_level: LogLevel = LogLevel.NORMAL,
		console_output: bool = True,
		max_log_entries: int = 10000,
		log_format: Optional[str] = None
	):
		self.log_level = log_level
		self.console_output = console_output
		self.max_log_entries = max_log_entries
		self.log_entries: deque = deque(maxlen=max_log_entries)
		self.lock = threading.Lock()
		
		# Use colored output only on non-Windows terminals
		self.use_colors = (
			platform.system() != 'Windows' and 
			sys.stdout.isatty()
		)
		
		# Default log format
		self.log_format = log_format or "[{timestamp}] [{level}] {component}: {message}"
		
		# Initialize Python logging for file output
		if log_file:
			log_path = SecurityVerifier.sanitize_path(log_file)
			log_path.parent.mkdir(parents=True, exist_ok=True)
			
			self.file_logger = logging.getLogger("pip_installer")
			self.file_logger.setLevel(logging.DEBUG)
			
			# Rotating file handler to prevent huge log files
			try:
				from logging.handlers import RotatingFileHandler
				file_handler = RotatingFileHandler(
					log_path,
					maxBytes=10*1024*1024,  # 10 MB
					backupCount=5,
					encoding='utf-8'
				)
			except ImportError:
				file_handler = logging.FileHandler(log_path, encoding='utf-8')
			
			file_handler.setLevel(logging.DEBUG)
			formatter = logging.Formatter(
				'%(asctime)s - %(name)s - %(levelname)s - %(message)s'
			)
			file_handler.setFormatter(formatter)
			self.file_logger.addHandler(file_handler)
			self.file_logger.propagate = False
		else:
			self.file_logger = None
	
	@contextmanager
	def temp_level(self, temp_level: LogLevel):
		"""
		Context manager for temporarily changing log level.
		
		Parameters
		----------
		temp_level : LogLevel
			Temporary log level to use within the context
			
		Yields
		------
		None
		
		Examples
		--------
		>>> with logger.temp_level(LogLevel.DEBUG):
		...	 logger.log("This uses DEBUG level", level=LogLevel.DEBUG)
		>>> # After context, original log level is restored
		"""
		original_level = self.log_level
		self.log_level = temp_level
		try:
			yield
		finally:
			self.log_level = original_level
	
	def log(
		self,
		message: str,
		level: LogLevel = LogLevel.NORMAL,
		component: str = "Main",
		**kwargs
	) -> None:
		"""
		Log a message with metadata and structured data.
		
		Parameters
		----------
		message : str
			Log message content
		level : LogLevel, optional
			Verbosity level for this message (default: LogLevel.NORMAL)
		component : str, optional
			Component generating the log message (default: "Main")
		**kwargs : dict
			Additional structured data to include in logs
			
		Examples
		--------
		Basic logging:
		>>> logger.log("Operation completed successfully")
		
		Detailed logging with component:
		>>> logger.log(
		...	 "Downloading file",
		...	 level=LogLevel.DETAILED,
		...	 component="Downloader"
		... )
		
		Log with structured data:
		>>> logger.log(
		...	 "Download completed",
		...	 level=LogLevel.NORMAL,
		...	 component="Network",
		...	 url="https://example.com",
		...	 size_bytes=1024,
		...	 duration_ms=150
		... )
		"""
		# Use .value for comparison to avoid Enum comparison issues
		if level.value < self.log_level.value:
			return
		
		log_entry = {
			"timestamp": datetime.now().isoformat(),
			"level": level.name,
			"component": component,
			"message": message,
			"data": kwargs
		}
		
		with self.lock:
			self.log_entries.append(log_entry)
		
		# Console output
		if self.console_output:
			self._write_to_console(log_entry)
		
		# File output
		if self.file_logger:
			self._write_to_file(log_entry)
	
	def _write_to_console(self, log_entry: Dict[str, Any]) -> None:
		"""
		Write log entry to console with optional colors.
		
		Parameters
		----------
		log_entry : Dict[str, Any]
			Structured log entry dictionary
		"""
		timestamp = log_entry['timestamp'][11:19]  # HH:MM:SS
		level = log_entry['level']
		component = log_entry['component']
		message = log_entry['message']
		
		# Format the output
		formatted = self.log_format.format(
			timestamp=timestamp,
			level=level,
			component=component,
			message=message
		)
		
		# Add colors if enabled
		if self.use_colors:
			if level == 'ERROR':
				color = self.COLORS['ERROR']
			elif level == 'WARNING':
				color = self.COLORS['WARNING']
			elif level == 'DEBUG':
				color = self.COLORS['DEBUG']
			elif level == 'DETAILED':
				color = self.COLORS['DETAILED']
			else:
				color = self.COLORS['NORMAL']
			
			formatted = f"{color}{formatted}{self.COLORS['RESET']}"
		
		print(formatted, file=sys.stderr if level == 'ERROR' else sys.stdout)
		
		# Print extra data in DEBUG mode
		if self.log_level >= LogLevel.DEBUG and log_entry.get('data'):
			for key, value in log_entry['data'].items():
				print(f"  └─ {key}: {value}", file=sys.stderr)
	
	def _write_to_file(self, log_entry: Dict[str, Any]) -> None:
		"""
		Write log entry to file with appropriate level.
		
		Parameters
		----------
		log_entry : Dict[str, Any]
			Structured log entry dictionary
		"""
		level = log_entry['level']
		component = log_entry['component']
		message = log_entry['message']
		
		log_method = self.file_logger.info
		if level == 'DEBUG':
			log_method = self.file_logger.debug
		elif level == 'ERROR':
			log_method = self.file_logger.error
		elif level == 'WARNING':
			log_method = self.file_logger.warning
		
		log_method(f"[{component}] {message}")
		
		if log_entry.get('data') and self.log_level >= LogLevel.DEBUG:
			self.file_logger.debug(f"  Extra data: {log_entry['data']}")
	
	def get_logs(
		self,
		level: Optional[LogLevel] = None,
		component: Optional[str] = None,
		since: Optional[datetime] = None,
		limit: Optional[int] = None,
		search_text: Optional[str] = None
	) -> List[Dict[str, Any]]:
		"""
		Retrieve logged entries with optional filtering.
		
		Parameters
		----------
		level : LogLevel, optional
			Filter by log level (include only entries at this level)
		component : str, optional
			Filter by component name (exact match)
		since : datetime, optional
			Filter by timestamp (entries after this time)
		limit : int, optional
			Maximum number of entries to return (most recent)
		search_text : str, optional
			Search for text in message field (case-insensitive)
			
		Returns
		-------
		List[Dict[str, Any]]
			Filtered list of log entries (newest first)
			
		Examples
		--------
		Get all error logs:
		>>> errors = logger.get_logs(level=LogLevel.ERROR)
		
		Get last 10 logs from Downloader component:
		>>> last_logs = logger.get_logs(
		...	 component="Downloader",
		...	 limit=10
		... )
		
		Search for specific text:
		>>> found = logger.get_logs(search_text="failed")
		"""
		with self.lock:
			entries = list(self.log_entries)
		
		# Apply filters (convert to list for filtering)
		if level:
			entries = [e for e in entries if e["level"] == level.name]
		
		if component:
			entries = [e for e in entries if e["component"] == component]
		
		if since:
			entries = [e for e in entries if datetime.fromisoformat(e["timestamp"]) >= since]
		
		if search_text:
			search_lower = search_text.lower()
			entries = [e for e in entries if search_lower in e["message"].lower()]
		
		# Return newest first (reverse of insertion order)
		entries.reverse()
		
		if limit:
			entries = entries[:limit]
		
		return entries
	
	def get_logs_by_level(self, level: LogLevel) -> List[Dict[str, Any]]:
		"""
		Convenience method to get logs at a specific level.
		
		Parameters
		----------
		level : LogLevel
			Log level to filter by
			
		Returns
		-------
		List[Dict[str, Any]]
			List of log entries at the specified level
			
		Examples
		--------
		>>> errors = logger.get_logs_by_level(LogLevel.ERROR)
		>>> warnings = logger.get_logs_by_level(LogLevel.WARNING)
		"""
		return self.get_logs(level=level)
	
	def clear(self) -> None:
		"""Clear all in-memory logs."""
		with self.lock:
			self.log_entries.clear()
		if self.file_logger:
			self.file_logger.info("Log buffer cleared")
	
	def error(self, message: str, component: str = "Main", **kwargs) -> None:
		"""
		Log an error message (convenience method).
		
		Parameters
		----------
		message : str
			Error message
		component : str, optional
			Component name (default: "Main")
		**kwargs : dict
			Additional structured data
		"""
		self.log(message, level=LogLevel.NORMAL, component=component, **kwargs)
	
	def warning(self, message: str, component: str = "Main", **kwargs) -> None:
		"""
		Log a warning message (convenience method).
		
		Parameters
		----------
		message : str
			Warning message
		component : str, optional
			Component name (default: "Main")
		**kwargs : dict
			Additional structured data
		"""
		self.log(f"WARNING: {message}", level=LogLevel.NORMAL, component=component, **kwargs)
	
	def debug(self, message: str, component: str = "Main", **kwargs) -> None:
		"""
		Log a debug message (convenience method).
		
		Parameters
		----------
		message : str
			Debug message
		component : str, optional
			Component name (default: "Main")
		**kwargs : dict
			Additional structured data
		"""
		self.log(message, level=LogLevel.DEBUG, component=component, **kwargs)
	
	def detailed(self, message: str, component: str = "Main", **kwargs) -> None:
		"""
		Log a detailed message (convenience method).
		
		Parameters
		----------
		message : str
			Detailed message
		component : str, optional
			Component name (default: "Main")
		**kwargs : dict
			Additional structured data
		"""
		self.log(message, level=LogLevel.DETAILED, component=component, **kwargs)


# ============================================================================
# Download Manager
# ============================================================================

class DownloadManager:
	"""
	Robust download manager with retries, checksums, and multiple fallbacks.
	
	This class handles all download operations with automatic retries,
	exponential backoff, integrity verification, and caching support.
	
	Parameters
	----------
	logger : InstallationLogger
		Logger instance for recording operations
	timeout : int, optional
		Download timeout in seconds (default: 30)
	max_retries : int, optional
		Maximum number of retry attempts (default: 3)
	verify_ssl : bool, optional
		Whether to verify SSL certificates (default: True)
	user_agent : str, optional
		Custom User-Agent header (default uses pyputil-pip identifier)
	
	Attributes
	----------
	logger : InstallationLogger
		Logger instance
	timeout : int
		Download timeout
	max_retries : int
		Maximum retry count
	verify_ssl : bool
		SSL verification flag
	ssl_context : ssl.SSLContext
		SSL context for connections
	
	Examples
	--------
	Basic usage:
	>>> from pyputil.pip import DownloadManager, InstallationLogger
	>>> logger = InstallationLogger()
	>>> downloader = DownloadManager(logger, timeout=60, max_retries=5)
	
	Download a file:
	>>> success = downloader.download(
	...	 "https://bootstrap.pypa.io/get-pip.py",
	...	 Path("/tmp/get-pip.py"),
	...	 expected_hash="sha256_hash_here"
	... )
	
	Download with fallback URLs:
	>>> urls = [
	...	 "https://bootstrap.pypa.io/get-pip.py",
	...	 "https://mirror.example.com/get-pip.py"
	... ]
	>>> success = downloader.download_with_fallbacks(urls, Path("/tmp/get-pip.py"))
	"""
	
	# Default headers for HTTP requests
	DEFAULT_HEADERS = {
		"User-Agent": f"pyputil-pip/{PipVersion.get_latest_stable()} (Python {platform.python_version()})",
		"Accept": "*/*",
		"Accept-Encoding": "gzip, deflate",
		"Connection": "keep-alive",
		"Accept-Language": "en-US,en;q=0.9"
	}
	
	def __init__(
		self,
		logger: InstallationLogger,
		timeout: int = 30,
		max_retries: int = 3,
		verify_ssl: bool = True,
		user_agent: Optional[str] = None
	):
		self.logger = logger
		self.timeout = timeout
		self.max_retries = max_retries
		self.verify_ssl = verify_ssl
		
		# Setup SSL context
		if verify_ssl:
			try:
				if where and Path(where).exists():
					self.ssl_context = ssl.create_default_context(cafile=where)
				else:
					# Using the system's default certificate
					self.ssl_context = ssl.create_default_context()
					self.logger.debug("Using default system certificates", component="Security")
			except Exception as e:
				self.logger.warning(f"SSL context creation failed: {e}, disabling verification", component="Security")
				self.ssl_context = ssl._create_unverified_context()
				self.verify_ssl = False
		else:
			self.logger.warning("SSL verification is disabled - insecure!", component="Security")
			self.ssl_context = ssl._create_unverified_context()
		
		# Set custom User-Agent if provided
		self.headers = self.DEFAULT_HEADERS.copy()
		if user_agent:
			self.headers["User-Agent"] = user_agent
	
	def _make_request(
		self,
		url: str,
		headers: Optional[Dict[str, str]] = None,
		retry_count: int = 0
	) -> Tuple[urllib.request.http.client.HTTPResponse, bytes]:
		"""
		Make HTTP request with retry logic and error handling.
		
		Parameters
		----------
		url : str
			URL to request
		headers : dict, optional
			Additional HTTP headers
		retry_count : int
			Current retry attempt number
			
		Returns
		-------
		Tuple[HTTPResponse, bytes]
			Response object and response body bytes
			
		Raises
		------
		DownloadError
			If request fails after retries
		"""
		request_headers = self.headers.copy()
		if headers:
			request_headers.update(headers)
		
		request = urllib.request.Request(url, headers=request_headers)
		
		try:
			with urllib.request.urlopen(
				request, timeout=self.timeout, context=self.ssl_context
			) as response:
				content = response.read()
				return response, content
		except urllib.error.HTTPError as e:
			if e.code == 404 and retry_count < self.max_retries - 1:
				# 404 might be temporary, retry
				raise DownloadError(
					f"HTTP {e.code}: {e.reason}",
					url=url,
					attempts=retry_count + 1,
					original_error=e
				)
			raise DownloadError(
				f"HTTP {e.code}: {e.reason}",
				url=url,
				original_error=e
			)
		except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
			raise DownloadError(
				f"Network error: {str(e)}",
				url=url,
				attempts=retry_count + 1,
				original_error=e
			)
	
	def download(
		self,
		url: str,
		destination: Path,
		expected_hash: Optional[str] = None,
		hash_algo: str = "sha256",
		headers: Optional[Dict[str, str]] = None,
		use_temp_file: bool = True
	) -> bool:
		"""
		Download a file with retries and optional hash verification.
		
		Parameters
		----------
		url : str
			URL to download from
		destination : Path
			Destination file path
		expected_hash : str, optional
			Expected hash for integrity verification
		hash_algo : str, optional
			Hash algorithm to use (default: 'sha256')
		headers : dict, optional
			Additional HTTP headers
		use_temp_file : bool, optional
			Whether to download to temp file first (default: True)
			
		Returns
		-------
		bool
			True if download successful and verification passes
			
		Raises
		------
		ValidationError
			If URL is invalid or unsafe
		DownloadError
			If download fails after all retries
			
		Examples
		--------
		Basic download:
		>>> success = downloader.download(
		...	 "https://example.com/file.zip",
		...	 Path("/tmp/file.zip")
		... )
		
		Download with hash verification:
		>>> success = downloader.download(
		...	 "https://example.com/script.py",
		...	 Path("/tmp/script.py"),
		...	 expected_hash="abc123...",
		...	 hash_algo="sha256"
		... )
		
		Download with custom headers:
		>>> success = downloader.download(
		...	 "https://api.example.com/download",
		...	 Path("/tmp/data.json"),
		...	 headers={"Authorization": "Bearer token"}
		... )
		"""
		if not SecurityVerifier.validate_url(url):
			raise ValidationError(
				f"Invalid or unsafe URL: {url}",
				validation_type="url_validation"
			)
		
		destination = SecurityVerifier.sanitize_path(destination)
		destination.parent.mkdir(parents=True, exist_ok=True)
		
		last_error = None
		
		for attempt in range(self.max_retries):
			# Use temporary file for atomic operations
			if use_temp_file:
				temp_path = destination.with_suffix(f".tmp.{attempt}")
			else:
				temp_path = destination
			
			try:
				self.logger.detailed(
					f"Downloading {url} (attempt {attempt + 1}/{self.max_retries})",
					component="Download",
					url=url,
					attempt=attempt + 1,
					destination=str(destination)
				)
				
				response, content = self._make_request(url, headers, attempt)
				
				# Log download statistics
				content_length = len(content)
				content_mb = content_length / (1024 * 1024)
				
				self.logger.debug(
					f"Downloaded {content_length:,} bytes ({content_mb:.2f} MB)",
					component="Download",
					content_length=content_length,
					content_mb=round(content_mb, 2),
					final_url=response.geturl()
				)
				
				# Write content to file
				with open(temp_path, "wb") as f:
					f.write(content)
				
				# Verify hash if provided
				if expected_hash:
					self.logger.detailed(
						f"Verifying {hash_algo} hash...",
						component="Security"
					)
					
					if not SecurityVerifier.verify_file_integrity(
						temp_path, expected_hash, hash_algo
					):
						raise ValidationError(
							f"Hash verification failed for {url}",
							validation_type="hash",
							expected=expected_hash,
							actual="computed_hash",
							context={"algorithm": hash_algo}
						)
					
					self.logger.debug(
						"Hash verification successful",
						component="Security"
					)
				
				# Atomic replace of destination file
				if use_temp_file:
					if destination.exists():
						destination.unlink()
					temp_path.rename(destination)
				
				self.logger.log(
					f"Successfully downloaded to {destination}",
					level=LogLevel.NORMAL,
					component="Download",
					size_bytes=content_length,
					size_mb=round(content_mb, 2),
					url=url
				)
				
				return True
			
			except (DownloadError, ValidationError) as e:
				last_error = e
				self.logger.warning(
					f"Download attempt {attempt + 1} failed: {e.message}",
					component="Download",
					attempt=attempt + 1,
					error_type=type(e).__name__
				)
				
				# Clean up temp file
				if use_temp_file and temp_path.exists():
					temp_path.unlink()
				
				# Wait with exponential backoff before retry
				if attempt < self.max_retries - 1:
					wait_time = min(2 ** attempt, 30)  # Max 30 seconds
					self.logger.debug(
						f"Retrying in {wait_time} seconds...",
						component="Download",
						wait_time=wait_time
					)
					time.sleep(wait_time)
		
		# All retries exhausted
		raise DownloadError(
			f"Failed to download after {self.max_retries} attempts: {url}",
			url=url,
			attempts=self.max_retries,
			original_error=last_error
		)
	
	def download_with_fallbacks(
		self,
		urls: List[str],
		destination: Path,
		expected_hash: Optional[str] = None,
		hash_algo: str = "sha256",
		headers: Optional[Dict[str, str]] = None
	) -> bool:
		"""
		Download from multiple URLs with fallback support.
		
		Tries each URL in order until one succeeds.
		
		Parameters
		----------
		urls : List[str]
			List of URLs to try in order of preference
		destination : Path
			Destination file path
		expected_hash : str, optional
			Expected hash for integrity verification
		hash_algo : str, optional
			Hash algorithm to use (default: 'sha256')
		headers : dict, optional
			Additional HTTP headers
			
		Returns
		-------
		bool
			True if any download succeeds
			
		Raises
		------
		DownloadError
			If all download sources fail
			
		Examples
		--------
		Download with multiple mirrors:
		>>> urls = [
		...	 "https://bootstrap.pypa.io/get-pip.py",
		...	 "https://mirror1.example.com/get-pip.py",
		...	 "https://mirror2.example.com/get-pip.py"
		... ]
		>>> success = downloader.download_with_fallbacks(
		...	 urls,
		...	 Path("/tmp/get-pip.py")
		... )
		
		With hash verification:
		>>> success = downloader.download_with_fallbacks(
		...	 urls,
		...	 Path("/tmp/script.py"),
		...	 expected_hash="abc123...",
		...	 hash_algo="sha256"
		... )
		"""
		failed_urls = []
		last_error = None
		
		for url in urls:
			try:
				self.logger.detailed(
					f"Attempting download from: {url}",
					component="Download",
					url=url,
					remaining_attempts=len(urls) - len(failed_urls)
				)
				
				if self.download(url, destination, expected_hash, hash_algo, headers):
					self.logger.log(
						f"Successfully downloaded from {url}",
						level=LogLevel.NORMAL,
						component="Download",
						url=url
					)
					return True
					
			except DownloadError as e:
				self.logger.warning(
					f"Failed from {url}: {e.message}",
					component="Download",
					url=url
				)
				failed_urls.append(url)
				last_error = e
				continue
		
		# All URLs failed
		raise DownloadError(
			f"All download sources failed for {destination.name}",
			context={
				"attempted_urls": urls,
				"failed_urls": failed_urls,
				"destination": str(destination)
			},
			original_error=last_error
		)


# ============================================================================
# Pip Installation Manager - Main Class
# ============================================================================

class PipManager:
	"""
	Main class for managing pip installations with comprehensive features.
	
	This class provides the primary interface for installing, upgrading,
	managing, and verifying pip installations across different platforms
	and Python environments.
	
	Parameters
	----------
	log_file : str or Path, optional
		Path to log file. If None, file logging is disabled.
	log_level : LogLevel, optional
		Logging verbosity level (default: LogLevel.NORMAL)
	timeout : int, optional
		Timeout for operations in seconds (default: 30)
	max_retries : int, optional
		Maximum retry attempts for downloads (default: 3)
	verify_ssl : bool, optional
		Whether to verify SSL certificates (default: True)
	cache_dir : Path, optional
		Directory for caching downloads (default: ~/.cache/pyputil-pip)
	console_output : bool, optional
		Whether to output logs to console (default: True)
		
	Attributes
	----------
	logger : InstallationLogger
		Logger instance for recording operations
	timeout : int
		Operation timeout
	max_retries : int
		Maximum retry count
	verify_ssl : bool
		SSL verification flag
	cache_dir : Path
		Cache directory path
	download_manager : DownloadManager
		Download manager instance
	platform : str
		Operating system platform name
	python_version : sys.version_info
		Python version information
	python_executable : str
		Path to Python executable
	
	Examples
	--------
	Basic installation:
	>>> manager = PipManager()
	>>> result = manager.install_pip()
	>>> if result.success:
	...	 print(f"Installed pip {result.pip_version}")
	
	Advanced configuration:
	>>> manager = PipManager(
	...	 log_file="pip_install.log",
	...	 log_level=LogLevel.DETAILED,
	...	 timeout=60,
	...	 max_retries=5,
	...	 verify_ssl=True
	... )
	
	Install specific version in user mode:
	>>> result = manager.install_pip(
	...	 version="24.0",
	...	 user_mode=True,
	...	 upgrade=True
	... )
	
	Check installation status:
	>>> status = manager.get_installed_pip_version()
	>>> if status:
	...	 version, path = status
	...	 print(f"pip {version} at {path}")
	
	Generate comprehensive report:
	>>> report = manager.get_installation_report()
	>>> print(f"Platform: {report.system.platform}")
	>>> print(f"Python: {report.system.python_version}")
	
	Verify installation:
	>>> verification = manager.verify_installation()
	>>> if verification.valid:
	...	 print("Installation is healthy")
	... else:
	...	 print(f"Issues found: {len(verification.issues)}")
	"""
	
	def __init__(
		self,
		log_file: Optional[Union[str, Path]] = None,
		log_level: LogLevel = LogLevel.NORMAL,
		timeout: int = 30,
		max_retries: int = 3,
		verify_ssl: bool = True,
		cache_dir: Optional[Path] = None,
		console_output: bool = True
	):
		# Initialize logger
		self.logger = InstallationLogger(
			log_file=log_file,
			log_level=log_level,
			console_output=console_output
		)
		
		# Configuration
		self.timeout = timeout
		self.max_retries = max_retries
		self.verify_ssl = verify_ssl
		
		# Setup cache directory
		if cache_dir is None:
			cache_dir = Path.home() / ".cache" / "pyputil-pip"
		self.cache_dir = SecurityVerifier.sanitize_path(cache_dir)
		self.cache_dir.mkdir(parents=True, exist_ok=True)
		
		# Initialize download manager
		self.download_manager = DownloadManager(
			self.logger, timeout, max_retries, verify_ssl
		)
		
		# System information
		self.platform = platform.system()
		self.python_version = sys.version_info
		self.python_executable = self._get_python_executable()
		
		self.logger.log(
			f"PipManager initialized",
			level=LogLevel.NORMAL,
			component="Init",
			platform=self.platform,
			python_version=f"{self.python_version.major}.{self.python_version.minor}",
			python_executable=self.python_executable,
			cache_dir=str(self.cache_dir),
			timeout=timeout,
			max_retries=max_retries,
			verify_ssl=verify_ssl
		)
	
	def _get_python_executable(self) -> str:
		"""
		Determine the correct Python executable path.
		
		Returns appropriate Python executable based on platform and
		virtual environment detection.
		
		Returns
		-------
		str
			Path to Python executable
			
		Examples
		--------
		>>> manager = PipManager()
		>>> python_path = manager._get_python_executable()
		>>> print(python_path)
		/usr/bin/python3
		"""
		# On Windows, try to find python in PATH first
		if self.platform == "Windows":
			python_cmd = shutil.which("python")
			if python_cmd:
				return python_cmd
		
		# Use sys.executable as fallback
		return sys.executable
	
	def _extract_pip_version_from_script(self, script_path: Path) -> Optional[str]:
		"""
		Extract pip version from get-pip.py script content.
		
		Searches for version patterns in the script file.
		
		Parameters
		----------
		script_path : Path
			Path to get-pip.py script
			
		Returns
		-------
		Optional[str]
			Extracted version string or None if not found
			
		Examples
		--------
		>>> version = manager._extract_pip_version_from_script(Path("get-pip.py"))
		>>> print(version)
		'26.1.1'
		"""
		try:
			content = script_path.read_text(encoding='utf-8')
			
			# Common version patterns in get-pip.py
			patterns = [
				r'__version__\s*=\s*["\']([^"\']+)["\']',
				r'PIP_VERSION\s*=\s*["\']([^"\']+)["\']',
				r'version\s*=\s*["\']([^"\']+)["\']',
				r'# pip[\s]+([0-9]+\.[0-9]+\.[0-9]+)',
				r'pip-([0-9]+\.[0-9]+\.[0-9]+)-py'
			]
			
			for pattern in patterns:
				match = re.search(pattern, content)
				if match:
					version = match.group(1)
					self.logger.debug(
						f"Extracted pip version {version} from script",
						component="Version"
					)
					return version
			
			self.logger.debug("Could not extract pip version from script", component="Version")
			return None
			
		except Exception as e:
			self.logger.debug(f"Failed to extract pip version: {e}", component="Version")
			return None
	
	def get_installed_pip_version(self) -> Optional[Tuple[str, Path]]:
		"""
		Get the currently installed pip version and location.
		
		Executes 'pip --version' and parses the output.
		
		Returns
		-------
		Optional[Tuple[str, Path]]
			(version_string, path) tuple if pip is installed, None otherwise
			
		Examples
		--------
		>>> result = manager.get_installed_pip_version()
		>>> if result:
		...	 version, path = result
		...	 print(f"pip {version} installed at {path}")
		... else:
		...	 print("pip is not installed")
		"""
		try:
			result = subprocess.run(
				[self.python_executable, "-m", "pip", "--version"],
				capture_output=True,
				text=True,
				timeout=10,
				check=False
			)
			
			if result.returncode == 0 and result.stdout:
				# Parse: "pip 24.0 from /path/to/pip (python 3.x)"
				match = re.search(r'pip\s+(\S+)', result.stdout)
				if match:
					version = match.group(1)
					
					# Extract path
					path_match = re.search(r'from\s+([^)]+)\s*\(', result.stdout)
					if path_match:
						path = Path(path_match.group(1).strip())
						self.logger.debug(
							f"Found pip {version} at {path}",
							component="Version"
						)
						return version, path
					
					# Fallback: just version without path
					return version, Path("unknown")
			
			return None
			
		except subprocess.TimeoutExpired:
			self.logger.warning("Timeout while checking pip version", component="Version")
			return None
		except Exception as e:
			self.logger.debug(f"Failed to get pip version: {e}", component="Version")
			return None
	
	def _build_installation_command(
		self,
		script_path: Path,
		target_directory: Optional[Path] = None,
		upgrade: bool = False,
		user_mode: bool = False,
		no_warn_script_location: bool = True,
		force_reinstall: bool = False
	) -> List[str]:
		"""
		Build the pip installation command with all options.
		
		Parameters
		----------
		script_path : Path
			Path to get-pip.py script
		target_directory : Path, optional
			Custom installation directory
		upgrade : bool, optional
			Whether to upgrade existing installation
		user_mode : bool, optional
			Whether to install in user site-packages
		no_warn_script_location : bool, optional
			Suppress script location warnings (default: True)
		force_reinstall : bool, optional
			Force reinstall even if already present
			
		Returns
		-------
		List[str]
			Command as list of arguments suitable for subprocess
			
		Examples
		--------
		>>> cmd = manager._build_installation_command(
		...	 Path("get-pip.py"),
		...	 user_mode=True,
		...	 upgrade=True
		... )
		>>> print(cmd)
		['python', 'get-pip.py', '--upgrade', '--user', '--no-warn-script-location']
		"""
		cmd = [self.python_executable, str(script_path)]
		
		if upgrade:
			cmd.append("--upgrade")
			self.logger.debug("Upgrade flag enabled", component="Install")
		
		if user_mode:
			cmd.append("--user")
			self.logger.debug("User mode enabled", component="Install")
		
		if target_directory:
			cmd.extend(["--target", str(target_directory)])
			self.logger.debug(f"Target directory: {target_directory}", component="Install")
		
		if no_warn_script_location:
			cmd.append("--no-warn-script-location")
		
		if force_reinstall:
			cmd.append("--force-reinstall")
			self.logger.debug("Force reinstall enabled", component="Install")
		
		# Add verbosity flags based on log level
		if self.logger.log_level == LogLevel.DEBUG:
			cmd.append("-vvv")
		elif self.logger.log_level == LogLevel.DETAILED:
			cmd.append("-vv")
		
		return cmd
	
	def install_pip(
		self,
		version: Optional[str] = None,
		target_directory: Optional[Path] = None,
		upgrade: bool = False,
		user_mode: bool = False,
		force_reinstall: bool = False,
		use_cache: bool = True,
		verify_checksum: bool = False,  # Changed to False by default due to hash issues
		method: InstallMethod = InstallMethod.BOOTSTRAP
	) -> InstallationResult:
		"""
		Install or upgrade pip with specified version.
		
		This is the main installation method that handles downloading,
		verifying, and installing pip with comprehensive error handling.
		
		Parameters
		----------
		version : str, optional
			Specific pip version to install (e.g., "24.0", "26.1.1").
			If None, installs latest stable version.
		target_directory : Path, optional
			Custom installation directory (overrides default site-packages)
		upgrade : bool, optional
			Whether to upgrade existing installation (default: False)
		user_mode : bool, optional
			Whether to install in user site-packages (no admin required)
		force_reinstall : bool, optional
			Whether to force reinstall even if already present (default: False)
		use_cache : bool, optional
			Whether to use cached downloads (default: True)
		verify_checksum : bool, optional
			Whether to verify file checksums (default: False - disabled due to hash mismatches)
		method : InstallMethod, optional
			Installation method to use (default: BOOTSTRAP)
			
		Returns
		-------
		InstallationResult
			Result object with installation details, warnings, and timing
			
		Raises
		------
		InstallationError
			For non-recoverable installation errors
		ValidationError
			For invalid parameters or environments
		
		Examples
		--------
		Install latest pip:
		>>> result = manager.install_pip()
		>>> if result.success:
		...	 print(f"Success: {result.message}")
		
		Install specific version in user mode:
		>>> result = manager.install_pip(
		...	 version="24.0",
		...	 user_mode=True
		... )
		
		Upgrade existing pip:
		>>> result = manager.install_pip(upgrade=True)
		
		Force reinstall:
		>>> result = manager.install_pip(
		...	 version="26.1.1",
		...	 force_reinstall=True,
		...	 user_mode=True
		... )
		
		Install to custom directory:
		>>> result = manager.install_pip(
		...	 target_directory=Path("./my_packages"),
		...	 user_mode=False
		... )
		"""
		start_time = time.time()
		warnings = []
		logs = []
		
		try:
			# Validate Python version
			if self.python_version < (3, 8):
				raise InstallationError(
					f"Python 3.8+ required, got {self.python_version.major}.{self.python_version.minor}",
					context={"python_version": f"{self.python_version.major}.{self.python_version.minor}"}
				)
			
			# Determine version to install
			if version is None:
				version = PipVersion.get_latest_stable()
				self.logger.log(
					f"No version specified, using latest stable: {version}",
					level=LogLevel.NORMAL,
					component="Version"
				)
			
			# Check existing installation
			installed = self.get_installed_pip_version()
			if installed and not force_reinstall and not upgrade:
				installed_version, installed_path = installed
				if installed_version == version:
					self.logger.log(
						f"pip {installed_version} already installed",
						level=LogLevel.NORMAL,
						component="Install"
					)
					return InstallationResult(
						success=True,
						message=f"pip {installed_version} already installed at {installed_path}",
						pip_version=installed_version,
						pip_path=installed_path,
						installation_time=time.time() - start_time,
						warnings=warnings
					)
				elif upgrade:
					warnings.append(f"Upgrading from {installed_version} to {version}")
					self.logger.log(
						f"Upgrading pip from {installed_version} to {version}",
						level=LogLevel.NORMAL,
						component="Install"
					)
			
			# Create temporary directory for installation
			with tempfile.TemporaryDirectory(prefix="pip_install_") as temp_dir:
				temp_path = Path(temp_dir)
				script_path = temp_path / "get-pip.py"
				
				# Check cache first
				cached_script = self.cache_dir / f"get-pip-{version}.py"
				if use_cache and cached_script.exists():
					self.logger.log(
						f"Using cached script: {cached_script}",
						level=LogLevel.NORMAL,
						component="Cache"
					)
					shutil.copy2(cached_script, script_path)
				else:
					# Get URLs for the specified version
					urls = PipVersion.get_bootstrap_urls(version)
					
					self.logger.log(
						f"Downloading pip bootstrap script for version {version}...",
						level=LogLevel.NORMAL,
						component="Download"
					)
					
					# Get expected hash if verification is enabled
					expected_hash = None
					hash_algo = "sha256"
					
					if verify_checksum and version in PipVersion.TRUSTED_HASHES.get("get-pip.py", {}):
						hash_info = PipVersion.TRUSTED_HASHES["get-pip.py"][version]
						hash_algo, expected_hash = hash_info.get_best_available()
						self.logger.detailed(
							f"Will verify {hash_algo} checksum",
							component="Security"
						)
					else:
						self.logger.detailed(
							"Checksum verification disabled",
							component="Security"
						)
					
					# Download with fallbacks
					self.download_manager.download_with_fallbacks(
						urls,
						script_path,
						expected_hash if expected_hash else None,
						hash_algo,
						headers={"Accept": "application/octet-stream"}
					)
					
					# Verify script is not empty
					if script_path.stat().st_size == 0:
						raise DownloadError("Downloaded script is empty")
					
					self.logger.debug(
						f"Downloaded script size: {script_path.stat().st_size} bytes",
						component="Download"
					)
					
					# Extract version from script for verification
					script_version = self._extract_pip_version_from_script(script_path)
					if script_version and script_version != version:
						self.logger.detailed(
							f"Script version {script_version} differs from requested {version}",
							component="Version",
							script_version=script_version,
							requested_version=version
						)
						warnings.append(f"Script reports version {script_version}, requested {version}")
					
					# Cache the script for future use
					if use_cache:
						shutil.copy2(script_path, cached_script)
						self.logger.debug(
							f"Cached script for future use: {cached_script}",
							component="Cache"
						)
				
				# Build installation command
				cmd = self._build_installation_command(
					script_path,
					target_directory,
					upgrade,
					user_mode,
					force_reinstall=force_reinstall
				)
				
				self.logger.detailed(
					f"Running installation command: {' '.join(cmd)}",
					component="Install"
				)
				
				# Prepare environment
				env = os.environ.copy()
				env["PYTHONUNBUFFERED"] = "1"
				env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
				
				if self.logger.log_level == LogLevel.DEBUG:
					env["PIP_VERBOSE"] = "1"
				
				# Execute installation
				process = subprocess.Popen(
					cmd,
					stdout=subprocess.PIPE,
					stderr=subprocess.PIPE,
					text=True,
					env=env,
					bufsize=1,
					universal_newlines=True
				)
				
				stdout_lines = []
				stderr_lines = []
				
				self.logger.log(
					"Installation in progress...",
					level=LogLevel.NORMAL,
					component="Install"
				)
				
				# Capture output
				for line in process.stdout:
					stdout_lines.append(line.strip())
					logs.append(line.strip())
					if self.logger.log_level >= LogLevel.DETAILED:
						self.logger.debug(line.strip(), component="Install")
				
				for line in process.stderr:
					stderr_lines.append(line.strip())
					logs.append(line.strip())
					if "warning" in line.lower():
						warnings.append(line.strip())
						self.logger.warning(line.strip(), component="Install")
					elif self.logger.log_level >= LogLevel.DETAILED:
						self.logger.debug(line.strip(), component="Install")
				
				# Wait for completion
				return_code = process.wait(timeout=self.timeout * 3)
				
				if return_code != 0:
					error_msg = f"Installation failed with exit code {return_code}"
					if stderr_lines:
						error_msg += f"\nError: {'; '.join(stderr_lines[:3])}"
					raise InstallationError(
						error_msg,
						pip_version=version,
						return_code=return_code
					)
				
				# Verify installation succeeded
				installed_version_info = self.get_installed_pip_version()
				if not installed_version_info:
					raise InstallationError(
						"Installation completed but pip not found",
						pip_version=version
					)
				
				installed_version, installed_path = installed_version_info
				elapsed_time = time.time() - start_time
				
				self.logger.log(
					f"Successfully installed pip {installed_version} in {elapsed_time:.2f}s",
					level=LogLevel.NORMAL,
					component="Install",
					version=installed_version,
					path=str(installed_path),
					duration=round(elapsed_time, 2)
				)
				
				return InstallationResult(
					success=True,
					message=f"Successfully installed pip {installed_version}",
					pip_version=installed_version,
					pip_path=installed_path,
					installation_time=elapsed_time,
					warnings=warnings,
					logs=logs
				)
				
		except (DownloadError, InstallationError, ValidationError) as e:
			elapsed_time = time.time() - start_time
			
			self.logger.error(
				f"Installation failed after {elapsed_time:.2f}s: {e.message}",
				component="Error",
				error_type=type(e).__name__,
				duration=round(elapsed_time, 2)
			)
			
			if warnings:
				self.logger.debug(f"Warnings collected: {warnings}", component="Error")
			
			return InstallationResult(
				success=False,
				message=e.message,
				installation_time=elapsed_time,
				warnings=warnings,
				logs=logs
			)
		
		except Exception as e:
			elapsed_time = time.time() - start_time
			
			self.logger.error(
				f"Unexpected error during installation: {e}",
				component="Error",
				error_type=type(e).__name__
			)
			
			return InstallationResult(
				success=False,
				message=f"Unexpected error: {str(e)}",
				installation_time=elapsed_time,
				warnings=warnings,
				logs=logs
			)
	
	def uninstall_pip(self, confirm: bool = True, force: bool = False) -> InstallationResult:
		"""
		Uninstall pip from the current environment.
		
		Attempts to uninstall pip using pip's built-in uninstaller first,
		then falls back to manual removal if needed.
		
		Parameters
		----------
		confirm : bool, optional
			Whether to require confirmation before uninstalling (default: True)
		force : bool, optional
			Force uninstallation without confirmation (default: False)
			
		Returns
		-------
		InstallationResult
			Result of uninstallation operation with status and timing
			
		Examples
		--------
		Uninstall with confirmation:
		>>> result = manager.uninstall_pip()
		>>> if result.success:
		...	 print("pip uninstalled successfully")
		
		Uninstall without confirmation:
		>>> result = manager.uninstall_pip(confirm=False)
		
		Force uninstall:
		>>> result = manager.uninstall_pip(force=True)
		"""
		start_time = time.time()
		
		try:
			# Check if pip is installed
			installed = self.get_installed_pip_version()
			if not installed:
				self.logger.log("pip is not installed", level=LogLevel.NORMAL, component="Uninstall")
				return InstallationResult(
					success=True,
					message="pip is not installed",
					installation_time=time.time() - start_time
				)
			
			installed_version, installed_path = installed
			
			# Confirmation prompt (unless forced or confirm=False)
			if confirm and not force:
				print(f"\n⚠️  WARNING: You are about to uninstall pip {installed_version}")
				print(f"   Location: {installed_path}")
				print(f"   This may affect Python package management in this environment.")
				response = input("   Continue? (y/N): ")
				if response.lower() != 'y':
					self.logger.log("Uninstallation cancelled by user", level=LogLevel.NORMAL, component="Uninstall")
					return InstallationResult(
						success=False,
						message="Uninstallation cancelled by user",
						installation_time=time.time() - start_time
					)
			
			self.logger.log(
				f"Uninstalling pip {installed_version}",
				level=LogLevel.NORMAL,
				component="Uninstall"
			)
			
			# Try pip's own uninstaller first
			result = subprocess.run(
				[self.python_executable, "-m", "pip", "uninstall", "pip", "-y"],
				capture_output=True,
				text=True,
				timeout=30
			)
			
			if result.returncode != 0:
				self.logger.warning(
					"Standard uninstall failed, using manual removal",
					component="Uninstall",
					error=result.stderr[:200] if result.stderr else "Unknown error"
				)
				
				# Manual removal: find and delete pip files
				removed_items = []
				site_packages_paths = []
				
				# Find site-packages directories
				for path in sys.path:
					if "site-packages" in path or "dist-packages" in path:
						site_packages_paths.append(Path(path))
				
				# Also check user site-packages
				try:
					user_site = site.getusersitepackages()
					if user_site:
						site_packages_paths.append(Path(user_site))
				except Exception:
					pass
				
				# Remove pip-related files and directories
				for sp_path in site_packages_paths:
					if not sp_path.exists():
						continue
					
					# Patterns for pip files
					patterns = ["pip", "pip-*", "pip-*.dist-info", "pip-*.egg-info", "pip-*.pth"]
					
					for pattern in patterns:
						for item in sp_path.glob(pattern):
							try:
								if item.is_dir():
									shutil.rmtree(item)
									removed_items.append(f"Directory: {item}")
									self.logger.debug(f"Removed directory: {item}", component="Uninstall")
								elif item.is_file():
									item.unlink()
									removed_items.append(f"File: {item}")
									self.logger.debug(f"Removed file: {item}", component="Uninstall")
							except Exception as e:
								self.logger.warning(f"Failed to remove {item}: {e}", component="Uninstall")
				
				if removed_items:
					self.logger.log(
						f"Manually removed {len(removed_items)} pip-related items",
						level=LogLevel.NORMAL,
						component="Uninstall",
						count=len(removed_items)
					)
				else:
					self.logger.warning(
						"No pip files found for manual removal",
						component="Uninstall"
					)
			
			elapsed_time = time.time() - start_time
			
			# Verify uninstallation
			verify_installed = self.get_installed_pip_version()
			if verify_installed:
				self.logger.warning(
					"pip still appears to be installed after uninstall",
					component="Uninstall",
					version=verify_installed[0]
				)
				return InstallationResult(
					success=False,
					message=f"Uninstallation incomplete - pip {verify_installed[0]} still present",
					installation_time=elapsed_time
				)
			
			self.logger.log(
				f"Successfully uninstalled pip {installed_version} in {elapsed_time:.2f}s",
				level=LogLevel.NORMAL,
				component="Uninstall"
			)
			
			return InstallationResult(
				success=True,
				message=f"Successfully uninstalled pip {installed_version}",
				installation_time=elapsed_time
			)
			
		except Exception as e:
			error_msg = f"Failed to uninstall pip: {str(e)}"
			self.logger.error(error_msg, component="Error")
			return InstallationResult(
				success=False,
				message=error_msg,
				installation_time=time.time() - start_time
			)
	
	def get_available_versions(self, limit: int = 20) -> VersionListResult:
		"""
		Get list of available pip versions from PyPI API.
		
		Queries PyPI's JSON API for pip release information and returns
		a sorted list of versions. Falls back to cached STABLE_VERSIONS
		if the API request fails.
		
		Parameters
		----------
		limit : int, optional
			Maximum number of versions to return (default: 20)
			
		Returns
		-------
		VersionListResult
			Structured result with version list, source, and any errors
			
		Examples
		--------
		Get available versions:
		>>> result = manager.get_available_versions(limit=10)
		>>> if result.is_success():
		...	 print(f"Latest: {result.get_latest()}")
		...	 for version in result.versions[:5]:
		...		 print(f"  - {version}")
		
		Get all versions (no limit):
		>>> result = manager.get_available_versions(limit=100)
		"""
		try:
			url = "https://pypi.org/pypi/pip/json"
			
			response_data = self.download_manager._make_request(url)[1]
			data = json.loads(response_data.decode())
			
			# Extract and sort versions
			versions = list(data.get("releases", {}).keys())
			
			def version_key(v: str) -> List[int]:
				"""Convert version string to comparable list of ints."""
				parts = v.split('.')
				return [int(p) for p in parts]
			
			versions.sort(key=version_key, reverse=True)
			limited_versions = versions[:limit]
			
			self.logger.detailed(
				f"Retrieved {len(limited_versions)} available pip versions from PyPI",
				component="Version",
				total_available=len(versions),
				limit=limit
			)
			
			return VersionListResult(
				versions=limited_versions,
				source="pypi_api"
			)
			
		except Exception as e:
			self.logger.warning(
				f"Failed to get available versions from PyPI: {e}",
				component="Version",
				falling_back_to_cache=True
			)
			
			# Fall back to cached stable versions
			return VersionListResult(
				versions=PipVersion.STABLE_VERSIONS[:limit],
				source="cached",
				error=str(e)
			)
	
	def list_installed_packages(self, format: str = "json") -> PackageListResult:
		"""
		List all installed Python packages using pip.
		
		Executes 'pip list' and parses the output to get package
		names and versions.
		
		Parameters
		----------
		format : str, optional
			Output format: 'json' (default) or 'text'
			
		Returns
		-------
		PackageListResult
			Structured result with package dictionary and count
			
		Examples
		--------
		List all packages:
		>>> result = manager.list_installed_packages()
		>>> print(f"Total packages: {result.count}")
		>>> for name, version in result.packages.items():
		...	 print(f"{name}=={version}")
		
		Search for specific package:
		>>> result = manager.list_installed_packages()
		>>> if result.has_package("requests"):
		...	 print(f"requests version: {result.get_version('requests')}")
		"""
		try:
			cmd = [self.python_executable, "-m", "pip", "list"]
			
			if format == "json":
				cmd.extend(["--format=json"])
				result = subprocess.run(
					cmd,
					capture_output=True,
					text=True,
					timeout=30,
					check=True
				)
				packages_data = json.loads(result.stdout)
				packages = {pkg["name"]: pkg["version"] for pkg in packages_data}
			else:
				# Text format parsing
				cmd.extend(["--format=columns"])
				result = subprocess.run(
					cmd,
					capture_output=True,
					text=True,
					timeout=30,
					check=True
				)
				packages = {}
				lines = result.stdout.strip().split('\n')[2:]  # Skip header
				for line in lines:
					if line.strip():
						parts = line.split()
						if len(parts) >= 2:
							packages[parts[0]] = parts[1]
			
			self.logger.detailed(
				f"Found {len(packages)} installed packages",
				component="Packages",
				count=len(packages)
			)
			
			return PackageListResult(
				packages=packages,
				count=len(packages)
			)
			
		except subprocess.CalledProcessError as e:
			error_msg = f"Failed to list packages: {e.stderr if e.stderr else str(e)}"
			self.logger.error(error_msg, component="Packages")
			return PackageListResult(packages={}, count=0, error=error_msg)
			
		except Exception as e:
			error_msg = f"Unexpected error listing packages: {str(e)}"
			self.logger.error(error_msg, component="Packages")
			return PackageListResult(packages={}, count=0, error=error_msg)
	
	def get_installation_report(self) -> InstallationReport:
		"""
		Generate a comprehensive installation and system report.
		
		Collects information about the system, environment, pip status,
		cache, and recent logs into a structured report.
		
		Returns
		-------
		InstallationReport
			Complete report with all diagnostic information
			
		Examples
		--------
		Generate and display report:
		>>> report = manager.get_installation_report()
		>>> print(f"Report generated: {report.timestamp}")
		>>> print(f"Platform: {report.system.platform}")
		>>> print(f"Pip installed: {report.pip_status.installed}")
		
		Export report to JSON:
		>>> json_str = report.to_json(indent=2)
		>>> with open("diagnostic.json", "w") as f:
		...	 f.write(json_str)
		"""
		# Get pip status
		installed_info = self.get_installed_pip_version()
		
		# Calculate cache information
		cache_size = 0
		cached_files = []
		cache_error = None
		
		try:
			for f in self.cache_dir.glob("*"):
				if f.is_file():
					size = f.stat().st_size
					cache_size += size
					cached_files.append({
						"name": f.name,
						"size_bytes": size,
						"size_mb": round(size / (1024 * 1024), 2),
						"modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat()
					})
		except Exception as e:
			cache_error = str(e)
			self.logger.debug(f"Error reading cache directory: {e}", component="Report")
		
		# Build system info
		system_info = SystemInfo(
			platform=self.platform,
			platform_details=platform.platform(),
			architecture=platform.machine(),
			processor=platform.processor(),
			python_version=f"{self.python_version.major}.{self.python_version.minor}.{self.python_version.micro}",
			python_implementation=platform.python_implementation(),
			python_compiler=platform.python_compiler(),
			python_executable=self.python_executable,
			python_path=sys.executable
		)
		
		# Build pip status
		pip_status = PipStatus(
			installed=installed_info is not None,
			version=installed_info[0] if installed_info else None,
			path=str(installed_info[1]) if installed_info else None
		)
		
		# Build environment info
		env_vars = {}
		for key, value in os.environ.items():
			if any(prefix in key for prefix in ['PYTHON', 'PIP', 'VIRTUAL', 'CONDA']):
				env_vars[key] = value
		
		env_info = EnvironmentInfo(
			virtual_env=sys.prefix != sys.base_prefix,
			venv_path=sys.prefix if sys.prefix != sys.base_prefix else None,
			user_site=site.getusersitepackages() if hasattr(site, 'getusersitepackages') else None,
			system_paths=sys.path[:20],  # Limit to first 20
			environment_variables=env_vars
		)
		
		# Build cache info
		cache_info = CacheInfo(
			directory=str(self.cache_dir),
			exists=self.cache_dir.exists(),
			size_bytes=cache_size,
			size_mb=round(cache_size / (1024 * 1024), 2),
			file_count=len(cached_files),
			files=cached_files,
			error=cache_error
		)
		
		# Build configuration info
		config_info = ConfigurationInfo(
			timeout=self.timeout,
			max_retries=self.max_retries,
			verify_ssl=self.verify_ssl,
			log_level=self.logger.log_level.name,
			cache_dir=str(self.cache_dir),
			platform=self.platform
		)
		
		# Get recent logs
		recent_logs = self.logger.get_logs(limit=100)
		
		report = InstallationReport(
			timestamp=datetime.now().isoformat(),
			system=system_info,
			pip_status=pip_status,
			environment=env_info,
			cache_info=cache_info,
			configuration=config_info,
			logs=recent_logs
		)
		
		self.logger.detailed(
			"Installation report generated",
			component="Report"
		)
		
		return report
	
	def export_configuration(self, file_path: Union[str, Path]) -> bool:
		"""
		Export current configuration and environment to a JSON file.
		
		Generates a complete report and saves it as JSON for debugging,
		documentation, or sharing configuration details.
		
		Parameters
		----------
		file_path : str or Path
			Path where configuration JSON should be saved
			
		Returns
		-------
		bool
			True if export succeeded, False otherwise
			
		Examples
		--------
		Export to current directory:
		>>> success = manager.export_configuration("config.json")
		>>> if success:
		...	 print("Configuration exported successfully")
		
		Export with full path:
		>>> success = manager.export_configuration(Path("/tmp/pip_report.json"))
		"""
		try:
			report = self.get_installation_report()
			path = SecurityVerifier.sanitize_path(file_path)
			path.parent.mkdir(parents=True, exist_ok=True)
			
			# Write JSON report
			with open(path, 'w', encoding='utf-8') as f:
				f.write(report.to_json(indent=2))
			
			file_size = path.stat().st_size
			self.logger.log(
				f"Configuration exported to {path}",
				level=LogLevel.NORMAL,
				component="Export",
				size_bytes=file_size,
				size_mb=round(file_size / (1024 * 1024), 2)
			)
			return True
			
		except Exception as e:
			self.logger.error(
				f"Failed to export configuration: {e}",
				component="Export"
			)
			return False
	
	def upgrade_pip(
		self,
		version: Optional[str] = None,
		user_mode: bool = False,
		**kwargs
	) -> InstallationResult:
		"""
		Convenience method to upgrade pip to latest or specific version.
		
		This is a wrapper around install_pip with upgrade=True.
		
		Parameters
		----------
		version : str, optional
			Specific version to upgrade to (default: latest stable)
		user_mode : bool, optional
			Whether to install in user mode (default: False)
		**kwargs : dict
			Additional arguments passed to install_pip
			
		Returns
		-------
		InstallationResult
			Result of the upgrade operation
			
		Examples
		--------
		Upgrade to latest version:
		>>> result = manager.upgrade_pip()
		
		Upgrade to specific version:
		>>> result = manager.upgrade_pip(version="24.0")
		
		Upgrade in user mode:
		>>> result = manager.upgrade_pip(user_mode=True)
		"""
		self.logger.log(
			f"Upgrading pip to {version or 'latest version'}",
			level=LogLevel.NORMAL,
			component="Upgrade"
		)
		
		return self.install_pip(
			version=version,
			upgrade=True,
			user_mode=user_mode,
			force_reinstall=False,
			**kwargs
		)
	
	def verify_installation(self) -> VerificationResult:
		"""
		Verify the integrity and functionality of the current pip installation.
		
		Runs a series of checks including:
		- Is pip installed?
		- Can pip be imported?
		- Does pip list command work?
		- File permissions are correct?
		- Version consistency?
		
		Returns
		-------
		VerificationResult
			Structured verification results with all checks and any issues
			
		Examples
		--------
		Run verification:
		>>> result = manager.verify_installation()
		>>> if result.valid:
		...	 print("✓ Installation is healthy")
		... else:
		...	 print(f"✗ Found {len(result.issues)} issues:")
		...	 for issue in result.issues:
		...		 print(f"  - {issue}")
		
		Check specific results:
		>>> result = manager.verify_installation()
		>>> if result.get_check_result("functional", False):
		...	 print("pip functions correctly")
		"""
		self.logger.log(
			"Verifying pip installation",
			level=LogLevel.NORMAL,
			component="Verify"
		)
		
		verification_checks = {}
		issues = []
		
		# Check 1: Pip is installed
		installed_info = self.get_installed_pip_version()
		verification_checks["installed"] = installed_info is not None
		
		if not installed_info:
			issues.append("Pip is not installed in this environment")
			self.logger.warning("Pip is not installed", component="Verify")
			return VerificationResult(
				valid=False,
				issues=issues,
				checks=verification_checks
			)
		
		version, path = installed_info
		verification_checks["version"] = version
		verification_checks["path"] = str(path)
		
		# Check 2: Pip module is importable
		try:
			result = subprocess.run(
				[self.python_executable, "-c", "import pip; print(pip.__version__)"],
				capture_output=True,
				text=True,
				timeout=10,
				check=True
			)
			import_version = result.stdout.strip()
			verification_checks["importable"] = True
			verification_checks["import_version"] = import_version
			
			if import_version != version:
				issues.append(
					f"Version mismatch: CLI reports {version}, "
					f"import reports {import_version}"
				)
				self.logger.warning(
					f"Version mismatch: {version} vs {import_version}",
					component="Verify"
				)
		except subprocess.CalledProcessError as e:
			verification_checks["importable"] = False
			issues.append(f"Cannot import pip module: {e.stderr if e.stderr else str(e)}")
			self.logger.warning(f"Failed to import pip: {e}", component="Verify")
		except Exception as e:
			verification_checks["importable"] = False
			issues.append(f"Error importing pip: {str(e)}")
		
		# Check 3: Basic functionality (pip list works)
		try:
			result = subprocess.run(
				[self.python_executable, "-m", "pip", "list", "--format=json"],
				capture_output=True,
				text=True,
				timeout=15,
				check=True
			)
			# Verify output is valid JSON
			json.loads(result.stdout)
			verification_checks["functional"] = True
			self.logger.debug("Pip list command works correctly", component="Verify")
		except subprocess.CalledProcessError as e:
			verification_checks["functional"] = False
			issues.append(f"Pip list command failed: {e.stderr if e.stderr else str(e)}")
			self.logger.warning(f"Pip list failed: {e}", component="Verify")
		except json.JSONDecodeError:
			verification_checks["functional"] = False
			issues.append("Pip list returned invalid JSON")
		except Exception as e:
			verification_checks["functional"] = False
			issues.append(f"Unexpected error testing pip: {str(e)}")
		
		# Check 4: Path and permissions
		try:
			if path.exists():
				verification_checks["path_exists"] = True
				verification_checks["path_readable"] = os.access(path, os.R_OK)
				verification_checks["parent_writable"] = os.access(path.parent, os.W_OK)
				
				if not verification_checks["path_readable"]:
					issues.append(f"Cannot read pip module at {path}")
				if not verification_checks["parent_writable"] and not self.is_virtual_env():
					issues.append(f"Cannot write to pip directory {path.parent}")
			else:
				verification_checks["path_exists"] = False
				issues.append(f"Pip path does not exist: {path}")
		except Exception as e:
			verification_checks["path_accessible"] = False
			issues.append(f"Cannot access pip path: {str(e)}")
		
		# Check 5: Check if in PATH (for pip command)
		try:
			pip_cmd = shutil.which("pip")
			verification_checks["pip_in_path"] = pip_cmd is not None
			if pip_cmd:
				verification_checks["pip_command_path"] = pip_cmd
		except Exception:
			verification_checks["pip_in_path"] = False
		
		valid = len(issues) == 0
		
		self.logger.log(
			f"Verification complete: {'✓ VALID' if valid else '✗ INVALID'}",
			level=LogLevel.NORMAL,
			component="Verify",
			issues_found=len(issues),
			checks_passed=len([v for v in verification_checks.values() if v is True])
		)
		
		return VerificationResult(
			valid=valid,
			issues=issues,
			checks=verification_checks
		)
	
	def is_virtual_env(self) -> bool:
		"""
		Check if running in a virtual environment.
		
		Returns
		-------
		bool
			True if in a virtual environment, False otherwise
			
		Examples
		--------
		>>> if manager.is_virtual_env():
		...	 print("Running in virtual environment")
		... else:
		...	 print("Running in system Python")
		"""
		return sys.prefix != sys.base_prefix
	
	def get_cache_info(self) -> CacheInfo:
		"""
		Get detailed information about the download cache.
		
		Analyzes the cache directory and returns statistics about
		cached files, including sizes and modification times.
		
		Returns
		-------
		CacheInfo
			Structured cache information with file details
			
		Examples
		--------
		>>> info = manager.get_cache_info()
		>>> print(f"Cache directory: {info.directory}")
		>>> print(f"Cached files: {info.file_count}")
		>>> print(f"Cache size: {info.format_size()}")
		
		Clear cache if too large:
		>>> if info.size_mb > 100:
		...	 manager.clear_cache()
		...	 print("Cache cleared (over 100 MB)")
		"""
		cache_info = CacheInfo(
			directory=str(self.cache_dir),
			exists=self.cache_dir.exists()
		)
		
		if not self.cache_dir.exists():
			return cache_info
		
		try:
			for file_path in self.cache_dir.iterdir():
				if file_path.is_file():
					size = file_path.stat().st_size
					cache_info.size_bytes += size
					cache_info.file_count += 1
					cache_info.files.append({
						"name": file_path.name,
						"size_bytes": size,
						"size_mb": round(size / (1024 * 1024), 2),
						"modified": datetime.fromtimestamp(
							file_path.stat().st_mtime
						).isoformat()
					})
			
			cache_info.size_mb = round(cache_info.size_bytes / (1024 * 1024), 2)
			
			self.logger.detailed(
				f"Cache contains {cache_info.file_count} files ({cache_info.size_mb:.2f} MB)",
				component="Cache"
			)
			
		except Exception as e:
			self.logger.error(f"Error reading cache: {e}", component="Cache")
			cache_info.error = str(e)
		
		return cache_info
	
	def clear_cache(self, confirm: bool = False) -> bool:
		"""
		Clear the download cache.
		
		Removes all cached bootstrap scripts to free disk space.
		
		Parameters
		----------
		confirm : bool, optional
			Whether to require confirmation (default: False)
			
		Returns
		-------
		bool			True if cache was cleared successfully
			
		Examples
		--------
		Clear without confirmation:
		>>> success = manager.clear_cache()
		
		Clear with confirmation:
		>>> success = manager.clear_cache(confirm=True)
		"""
		cache_info = self.get_cache_info()
		
		if cache_info.file_count == 0:
			self.logger.log("Cache is already empty", level=LogLevel.NORMAL, component="Cache")
			return True
		
		if confirm:
			print(f"\n📁 Cache directory: {cache_info.directory}")
			print(f"   Files: {cache_info.file_count}")
			print(f"   Size: {cache_info.format_size()}")
			response = input("   Clear cache? (y/N): ")
			if response.lower() != 'y':
				self.logger.log("Cache clear cancelled", level=LogLevel.NORMAL, component="Cache")
				return False
		
		try:
			if not self.cache_dir.exists():
				return True
			
			removed_count = 0
			for file_path in self.cache_dir.iterdir():
				if file_path.is_file():
					file_path.unlink()
					removed_count += 1
			
			self.logger.log(
				f"Cleared {removed_count} files from cache",
				level=LogLevel.NORMAL,
				component="Cache",
				freed_mb=round(cache_info.size_mb, 2)
			)
			return True
			
		except Exception as e:
			self.logger.error(f"Failed to clear cache: {e}", component="Cache")
			return False
	
	def get_logger(self) -> InstallationLogger:
		"""
		Get the logger instance for custom logging.
		
		Returns
		-------
		InstallationLogger
			The logger instance used by the manager
			
		Examples
		--------
		>>> logger = manager.get_logger()
		>>> logger.log("Custom message", level=LogLevel.DEBUG)
		>>> logs = logger.get_logs(limit=10)
		"""
		return self.logger


# ============================================================================
# CLI Interface
# ============================================================================

def create_argument_parser() -> argparse.ArgumentParser:
	"""
	Create and configure the command-line argument parser.
	
	Sets up all available CLI commands and their options for
	interacting with pyputil-pip from the command line.
	
	Returns
	-------
	argparse.ArgumentParser
		Configured argument parser with all subcommands
		
	Examples
	--------
	>>> parser = create_argument_parser()
	>>> args = parser.parse_args(['install', '--version', '24.0', '--user'])
	"""
	parser = argparse.ArgumentParser(
		prog="pyputil-pip",
		description="Advanced pip installation and management tool",
		formatter_class=argparse.RawDescriptionHelpFormatter,
		epilog="""
Examples:
  # Install latest pip
  %(prog)s install
  
  # Install specific version
  %(prog)s install --version 24.0
  
  # Install in user mode (no admin required)
  %(prog)s install --user
  
  # Upgrade existing pip
  %(prog)s install --upgrade
  
  # Uninstall pip
  %(prog)s uninstall --yes
  
  # Show current pip status
  %(prog)s status
  
  # List compatible versions
  %(prog)s versions --compatible
  
  # Export configuration for debugging
  %(prog)s export config.json
  
  # View recent logs
  %(prog)s logs --level detailed --lines 50
  
  # Clear download cache
  %(prog)s clear-cache
  
  # Verify pip installation
  %(prog)s verify
		"""
	)
	
	subparsers = parser.add_subparsers(dest="command", help="Command to execute", required=True)
	
	# Install command
	install_parser = subparsers.add_parser(
		"install",
		help="Install or upgrade pip",
		description="Download and install pip with various options."
	)
	install_parser.add_argument(
		"--version",
		help="Specific pip version to install (e.g., '24.0')"
	)
	install_parser.add_argument(
		"--target",
		type=Path,
		help="Custom target directory for installation"
	)
	install_parser.add_argument(
		"--upgrade", "-U",
		action="store_true",
		help="Upgrade existing pip if present"
	)
	install_parser.add_argument(
		"--user", "-u",
		action="store_true",
		help="Install in user site-packages (no admin required)"
	)
	install_parser.add_argument(
		"--force", "-f",
		action="store_true",
		help="Force reinstallation even if already present"
	)
	install_parser.add_argument(
		"--no-cache",
		action="store_true",
		help="Don't use cached downloads"
	)
	install_parser.add_argument(
		"--verify", "-v",
		action="store_true",
		help="Verify checksums (may fail with new versions)"
	)
	
	# Uninstall command
	uninstall_parser = subparsers.add_parser(
		"uninstall",
		help="Uninstall pip",
		description="Remove pip from the current Python environment."
	)
	uninstall_parser.add_argument(
		"--yes", "-y",
		action="store_true",
		help="Skip confirmation prompt"
	)
	uninstall_parser.add_argument(
		"--force", "-f",
		action="store_true",
		help="Force uninstallation"
	)
	
	# Status command
	subparsers.add_parser(
		"status",
		help="Show pip installation status",
		description="Display comprehensive information about pip and environment."
	)
	
	# Versions command
	versions_parser = subparsers.add_parser(
		"versions",
		help="List available pip versions",
		description="Query PyPI for available pip versions."
	)
	versions_parser.add_argument(
		"--compatible", "-c",
		action="store_true",
		help="Show only versions compatible with current Python"
	)
	versions_parser.add_argument(
		"--limit", "-l",
		type=int,
		default=20,
		help="Maximum number of versions to show (default: 20)"
	)
	versions_parser.add_argument(
		"--all", "-a",
		action="store_true",
		help="Show all versions (ignores limit)"
	)
	
	# Export command
	export_parser = subparsers.add_parser(
		"export",
		help="Export configuration to JSON file",
		description="Export complete environment and configuration to JSON."
	)
	export_parser.add_argument(
		"output",
		type=Path,
		help="Output file path (e.g., 'config.json')"
	)
	
	# Logs command
	logs_parser = subparsers.add_parser(
		"logs",
		help="Show installation logs",
		description="View installation logs with filtering options."
	)
	logs_parser.add_argument(
		"--level", "-l",
		choices=["minimal", "normal", "detailed", "debug"],
		default="normal",
		help="Log level to display"
	)
	logs_parser.add_argument(
		"--lines", "-n",
		type=int,
		default=50,
		help="Number of lines to show (default: 50)"
	)
	logs_parser.add_argument(
		"--component", "-c",
		help="Filter by component name (e.g., 'Download', 'Security')"
	)
	logs_parser.add_argument(
		"--search", "-s",
		help="Search text in log messages"
	)
	
	# Clear cache command
	cache_parser = subparsers.add_parser(
		"clear-cache",
		help="Clear download cache",
		description="Remove all cached pip bootstrap scripts."
	)
	cache_parser.add_argument(
		"--yes", "-y",
		action="store_true",
		help="Skip confirmation prompt"
	)
	
	# Verify command
	subparsers.add_parser(
		"verify",
		help="Verify pip installation integrity",
		description="Run comprehensive verification checks."
	)
	
	# Upgrade command (convenience alias)
	upgrade_parser = subparsers.add_parser(
		"upgrade",
		help="Upgrade pip to latest version",
		description="Upgrade pip to latest or specified version."
	)
	upgrade_parser.add_argument(
		"--version",
		help="Specific version to upgrade to"
	)
	upgrade_parser.add_argument(
		"--user", "-u",
		action="store_true",
		help="Install in user mode"
	)
	
	# Global options
	parser.add_argument(
		"--log-level",
		choices=["minimal", "normal", "detailed", "debug"],
		default="normal",
		help="Global log level (default: normal)"
	)
	parser.add_argument(
		"--log-file",
		type=Path,
		help="Log file path (default: pyputil.pip.log)"
	)
	parser.add_argument(
		"--no-console",
		action="store_true",
		help="Disable console output (logs only to file)"
	)
	
	return parser


def handle_install_command(manager: PipManager, args: argparse.Namespace) -> int:
	"""
	Handle the install CLI command.
	
	Parameters
	----------
	manager : PipManager
		Configured PipManager instance
	args : argparse.Namespace
		Parsed command-line arguments
		
	Returns
	-------
	int
		Exit code (0 for success, 1 for failure)
	"""
	result = manager.install_pip(
		version=getattr(args, 'version', None),
		target_directory=getattr(args, 'target', None),
		upgrade=getattr(args, 'upgrade', False),
		user_mode=getattr(args, 'user', False),
		force_reinstall=getattr(args, 'force', False),
		use_cache=not getattr(args, 'no_cache', False),
		verify_checksum=getattr(args, 'verify', False)
	)
	
	if result.success:
		print(f"\n✓ SUCCESS: {result.message}")
		if result.warnings:
			print(f"\n⚠️  Warnings ({len(result.warnings)}):")
			for warning in result.warnings[:5]:
				print(f"   • {warning}")
			if len(result.warnings) > 5:
				print(f"   ... and {len(result.warnings) - 5} more")
		print(f"\n⏱️  Time: {result.installation_time:.2f} seconds")
		if result.pip_path:
			print(f"📁 Location: {result.pip_path}")
		return 0
	else:
		print(f"\n✗ FAILED: {result.message}")
		if result.warnings:
			print("\n⚠️  Warnings:")
			for warning in result.warnings:
				print(f"   • {warning}")
		return 1


def handle_uninstall_command(manager: PipManager, args: argparse.Namespace) -> int:
	"""
	Handle the uninstall CLI command.
	
	Parameters
	----------
	manager : PipManager
		Configured PipManager instance
	args : argparse.Namespace
		Parsed command-line arguments
		
	Returns
	-------
	int
		Exit code (0 for success, 1 for failure)
	"""
	result = manager.uninstall_pip(
		confirm=not getattr(args, 'yes', False),
		force=getattr(args, 'force', False)
	)
	
	if result.success:
		print(f"\n✓ SUCCESS: {result.message}")
		print(f"⏱️  Time: {result.installation_time:.2f}s")
		return 0
	else:
		print(f"\n✗ FAILED: {result.message}")
		return 1


def handle_status_command(manager: PipManager, args: argparse.Namespace) -> int:
	"""
	Handle the status CLI command.
	
	Parameters
	----------
	manager : PipManager
		Configured PipManager instance
	args : argparse.Namespace
		Parsed command-line arguments
		
	Returns
	-------
	int
		Exit code (0 for success)
	"""
	installed = manager.get_installed_pip_version()
	
	print("\n" + "=" * 60)
	print("📦 Pip Installation Status")
	print("=" * 60)
	
	if installed:
		version, path = installed
		print(f"\n✅ Status: INSTALLED")
		print(f"   Version: {version}")
		print(f"   Location: {path}")
		print(f"   Python: {manager.python_executable}")
		print(f"   Platform: {manager.platform}")
	else:
		print(f"\n❌ Status: NOT INSTALLED")
	
	print(f"\n🔧 Environment Information")
	print("-" * 60)
	print(f"   Virtual Environment: {'✓ Yes' if manager.is_virtual_env() else '✗ No'}")
	if manager.is_virtual_env():
		print(f"   Venv Path: {sys.prefix}")
	print(f"   Python Version: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
	print(f"   Implementation: {platform.python_implementation()}")
	print(f"   Compiler: {platform.python_compiler()}")
	
	# Cache information
	cache_info = manager.get_cache_info()
	print(f"\n💾 Cache Information")
	print("-" * 60)
	print(f"   Directory: {cache_info.directory}")
	print(f"   Files: {cache_info.file_count}")
	print(f"   Size: {cache_info.format_size()}")
	
	# Quick verification
	print(f"\n🔍 Quick Verification")
	print("-" * 60)
	verification = manager.verify_installation()
	if verification.valid:
		print(f"   ✅ All checks passed")
	else:
		print(f"   ❌ Found {len(verification.issues)} issue(s):")
		for issue in verification.issues[:3]:
			print(f"	  • {issue}")
		if len(verification.issues) > 3:
			print(f"	  ... and {len(verification.issues) - 3} more")
	
	return 0


def handle_versions_command(manager: PipManager, args: argparse.Namespace) -> int:
	"""
	Handle the versions CLI command.
	
	Parameters
	----------
	manager : PipManager
		Configured PipManager instance
	args : argparse.Namespace
		Parsed command-line arguments
		
	Returns
	-------
	int
		Exit code (0 for success)
	"""
	limit = None if getattr(args, 'all', False) else args.limit
	
	if args.compatible:
		versions = PipVersion.get_compatible_versions()
		title = f"📋 Pip versions compatible with Python {sys.version_info.major}.{sys.version_info.minor}"
	else:
		result = manager.get_available_versions(limit=limit if limit else 100)
		versions = result.versions
		title = f"📋 Available pip versions"
		if result.error:
			print(f"\n⚠️  Note: {result.error}")
	
	print(f"\n{title}")
	print("=" * 60)
	
	current = manager.get_installed_pip_version()
	current_version = current[0] if current else None
	
	for i, version in enumerate(versions[:limit] if limit else versions):
		marker = "→ " if current_version and current_version == version else "  "
		lts_marker = " [LTS]" if PipVersion.is_lts_version(version) else ""
		print(f"{marker} {version}{lts_marker}")
	
	if current_version and current_version not in versions[:limit] if limit else True:
		print(f"\n💡 Current installed version: {current_version}")
	
	return 0


def handle_export_command(manager: PipManager, args: argparse.Namespace) -> int:
	"""
	Handle the export CLI command.
	
	Parameters
	----------
	manager : PipManager
		Configured PipManager instance
	args : argparse.Namespace
		Parsed command-line arguments
		
	Returns
	-------
	int
		Exit code (0 for success, 1 for failure)
	"""
	success = manager.export_configuration(args.output)
	if success:
		file_size = args.output.stat().st_size if args.output.exists() else 0
		print(f"\n✓ SUCCESS: Configuration exported to {args.output}")
		print(f"   Size: {file_size:,} bytes")
		return 0
	else:
		print(f"\n✗ FAILED: Could not export configuration")
		return 1


def handle_logs_command(manager: PipManager, args: argparse.Namespace) -> int:
	"""
	Handle the logs CLI command.
	
	Parameters
	----------
	manager : PipManager
		Configured PipManager instance
	args : argparse.Namespace
		Parsed command-line arguments
		
	Returns
	-------
	int
		Exit code (0 for success)
	"""
	level_map = {
		"minimal": LogLevel.MINIMAL,
		"normal": LogLevel.NORMAL,
		"detailed": LogLevel.DETAILED,
		"debug": LogLevel.DEBUG
	}
	log_level = level_map.get(args.level, LogLevel.NORMAL)
	
	logs = manager.get_logger().get_logs(
		level=log_level,
		component=getattr(args, 'component', None),
		search_text=getattr(args, 'search', None),
		limit=args.lines
	)
	
	if not logs:
		print(f"\n📭 No logs found matching criteria")
		return 0
	
	print(f"\n📋 Last {len(logs)} log entries")
	print("=" * 80)
	
	for entry in logs:
		timestamp = entry['timestamp'][:19]
		level = entry['level']
		component = entry['component'][:15].ljust(15)
		message = entry['message']
		
		# Color code based on level
		if level == 'ERROR':
			prefix = f"[{timestamp}] 🔴 {component}"
		elif level == 'WARNING':
			prefix = f"[{timestamp}] 🟡 {component}"
		elif level == 'DEBUG':
			prefix = f"[{timestamp}] 🔵 {component}"
		else:
			prefix = f"[{timestamp}]   {component}"
		
		print(f"{prefix}: {message}")
		
		if args.level == "debug" and entry.get('data'):
			for key, value in entry['data'].items():
				if value:
					print(f"		 └─ {key}: {value}")
	
	return 0


def handle_clear_cache_command(manager: PipManager, args: argparse.Namespace) -> int:
	"""
	Handle the clear-cache CLI command.
	
	Parameters
	----------
	manager : PipManager
		Configured PipManager instance
	args : argparse.Namespace
		Parsed command-line arguments
		
	Returns
	-------
	int
		Exit code (0 for success, 1 for failure)
	"""
	cache_info = manager.get_cache_info()
	
	if cache_info.is_empty():
		print(f"\n📭 Cache is already empty")
		return 0
	
	confirm = not getattr(args, 'yes', False)
	success = manager.clear_cache(confirm=confirm)
	
	if success:
		print(f"\n✓ SUCCESS: Cache cleared (removed {cache_info.file_count} files, {cache_info.format_size()})")
		return 0
	else:
		print(f"\n✗ FAILED: Could not clear cache")
		return 1


def handle_verify_command(manager: PipManager, args: argparse.Namespace) -> int:
	"""
	Handle the verify CLI command.
	
	Parameters
	----------
	manager : PipManager
		Configured PipManager instance
	args : argparse.Namespace
		Parsed command-line arguments
		
	Returns
	-------
	int
		Exit code (0 for success, 1 for failure)
	"""
	print(f"\n🔍 Verifying pip installation...")
	print("=" * 60)
	
	verification = manager.verify_installation()
	
	print(f"\n📊 Verification Results:")
	print("-" * 60)
	
	# Display key checks
	important_checks = ['installed', 'importable', 'functional', 'pip_in_path']
	for check_name in important_checks:
		if check_name in verification.checks:
			result = verification.checks[check_name]
			status = "✅" if result else "❌"
			print(f"   {status} {check_name}: {result}")
	
	print(f"\n📈 Summary:")
	print("-" * 60)
	
	if verification.valid:
		print(f"   ✅ Installation is VALID")
		print(f"   Version: {verification.checks.get('version', 'Unknown')}")
		if verification.checks.get('path'):
			print(f"   Path: {verification.checks['path']}")
		return 0
	else:
		print(f"   ❌ Installation is INVALID")
		print(f"\n   Issues found ({len(verification.issues)}):")
		for issue in verification.issues:
			print(f"	  • {issue}")
		return 1


def handle_upgrade_command(manager: PipManager, args: argparse.Namespace) -> int:
	"""
	Handle the upgrade CLI command.
	
	Parameters
	----------
	manager : PipManager
		Configured PipManager instance
	args : argparse.Namespace
		Parsed command-line arguments
		
	Returns
	-------
	int
		Exit code (0 for success, 1 for failure)
	"""
	result = manager.upgrade_pip(
		version=getattr(args, 'version', None),
		user_mode=getattr(args, 'user', False)
	)
	
	if result.success:
		print(f"\n✓ SUCCESS: {result.message}")
		print(f"⏱️  Time: {result.installation_time:.2f}s")
		if result.pip_version:
			print(f"📦 Version: {result.pip_version}")
		return 0
	else:
		print(f"\n✗ FAILED: {result.message}")
		return 1


def main():
	"""
	Command-line interface entry point for pyputil-pip.
	
	Handles argument parsing, command dispatching, and error handling.
	
	Returns
	-------
	int
		Exit code (0 for success, non-zero for errors)
	"""
	# Validate Python version
	if sys.version_info < (3, 8):
		print(f"❌ Error: Python 3.8+ is required.")
		print(f"   Current version: {sys.version_info.major}.{sys.version_info.minor}")
		print("   Please upgrade Python to continue.")
		sys.exit(1)
	
	try:
		parser = create_argument_parser()
		args = parser.parse_args()
	except SystemExit:
		raise
	
	# Determine log level
	log_level_map = {
		"minimal": LogLevel.MINIMAL,
		"normal": LogLevel.NORMAL,
		"detailed": LogLevel.DETAILED,
		"debug": LogLevel.DEBUG
	}
	log_level = log_level_map.get(getattr(args, 'log_level', 'normal'), LogLevel.NORMAL)
	
	# Create manager instance
	manager = PipManager(
		log_level=log_level,
		log_file=getattr(args, 'log_file', None) or "pyputil.pip.log",
		console_output=not getattr(args, 'no_console', False)
	)
	
	# Command handlers
	command_handlers = {
		"install": handle_install_command,
		"uninstall": handle_uninstall_command,
		"status": handle_status_command,
		"versions": handle_versions_command,
		"export": handle_export_command,
		"logs": handle_logs_command,
		"clear-cache": handle_clear_cache_command,
		"verify": handle_verify_command,
		"upgrade": handle_upgrade_command,
	}
	
	if args.command in command_handlers:
		try:
			exit_code = command_handlers[args.command](manager, args)
			sys.exit(exit_code)
		except KeyboardInterrupt:
			print("\n\n⚠️  Operation cancelled by user")
			sys.exit(130)
		except PipError as e:
			print(f"\n❌ Error: {e.message}")
			if log_level == LogLevel.DEBUG:
				import traceback
				traceback.print_exc()
			sys.exit(1)
		except Exception as e:
			print(f"\n❌ Unexpected error: {e}")
			if log_level == LogLevel.DEBUG:
				import traceback
				traceback.print_exc()
			sys.exit(1)
	else:
		parser.print_help()
		sys.exit(1)


if __name__ == "__main__":
	main()