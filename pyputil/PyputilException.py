#!/usr/bin/env python3

# -*- coding: utf-8 -*-

class NotAFileError(Exception):
    pass


class ModuleExistsError(Exception):
    pass


class PackageNotFoundError(Exception):
    pass


class FileComparisonError(Exception):
    pass


class AccessError(AttributeError):

    def __init__(self, message: str, *, suggestion: str = None, docs_url: str = None):
        self.message = message
        self.suggestion = suggestion
        self.docs_url = docs_url
        error_msg = f"{message}{f' {suggestion}' if suggestion else ''}"
        super().__init__(error_msg)


class DataImportError(Exception):
    """Custom exception for data import operations"""

    def __init__(self, message: str, file_path: str = None, error_type: str = None):
        self.message = message
        self.file_path = file_path
        self.error_type = error_type
        super().__init__(self.message)


class ImportBlockedError(RuntimeError):
    pass


PyputilException = (
    NotAFileError,
    ModuleExistsError,
    PackageNotFoundError,
    AccessError,
    DataImportError,
    ImportBlockedError,
    FileComparisonError,
)
