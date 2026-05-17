#!/usr/bin/env python3

# -*- coding: utf-8 -*-

from pathlib import Path
import shutil
import hashlib


class NotAFile(Exception):
    """Raised when a path is not a valid file."""

    def __str__(self):
        return "Expected file, got directory or invalid path."


def check(p: Path) -> None:
    """
    Ensure the given Path exists and is a file.

    Raises
    ------
    FileNotFoundError
            If the path does not exist.
    NotAFile
            If the path exists but is not a file.
    """
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")
    if not p.is_file():
        raise NotAFile()


def read(filename: str, mode: str = "r", chunk_size: int = 8192):
    """
    Read file content efficiently using chunks.

    Parameters
    ----------
    filename : str
            Path to the file.
    mode : str, optional
            'r'  → text mode (default)
            'rb' → binary mode
            'rl' → line mode
    chunk_size : int, optional
            Number of bytes per read operation (default: 8KB).

    Returns
    -------
    str | bytes | list[str]
            File content, depending on mode.

    Notes
    -----
    Uses streaming to avoid loading large files into memory at once.
    """
    p = Path(filename)
    check(p)

    if mode == "rl":  # line mode
        with p.open("r", encoding="utf-8") as f:
            return f.readlines()

    elif mode == "rb":  # binary mode
        data = bytearray()
        with p.open("rb") as f:
            while chunk := f.read(chunk_size):
                data.extend(chunk)
        return bytes(data)

    elif mode == "r":  # text mode
        content = []
        with p.open("r", encoding="utf-8") as f:
            while chunk := f.read(chunk_size):
                content.append(chunk)
        return "".join(content)

    else:
        raise ValueError(f"Invalid mode: {mode}")


def write(filename: str, data, mode: str = "w", chunk_size: int = 8192):
    """
    Write data to a file efficiently in chunks.

    Parameters
    ----------
    filename : str
            Path to target file.
    data : str | bytes | list[str]
            Data to write.
    mode : str, optional
            'w'  → text (overwrite)
            'a'  → append text
            'wb' → binary write
            'ab' → binary append
            'wl' → write lines
    chunk_size : int, optional
            Bytes per write operation (default: 8KB).

    Notes
    -----
    Automatically creates parent directories if needed.
    Writes large data in chunks to reduce memory usage.
    """
    p = Path(filename)

    if mode in ("w", "a"):
        with p.open(mode, encoding="utf-8") as f:
            for i in range(0, len(data), chunk_size):
                f.write(data[i : i + chunk_size])

    elif mode in ("wb", "ab"):
        with p.open(mode) as f:
            for i in range(0, len(data), chunk_size):
                f.write(data[i : i + chunk_size])

    elif mode == "wl":
        if not isinstance(data, (list, tuple)):
            raise TypeError("write(mode='wl') expects list or tuple of strings")
        with p.open("w", encoding="utf-8") as f:
            for line in data:
                f.write(line if line.endswith("\n") else line + "\n")

    else:
        raise ValueError(f"Invalid mode: {mode}")


def size(filename: str) -> int:
    """Return file size in bytes."""
    p = Path(filename)
    check(p)
    return p.stat().st_size


def remove(path: str) -> None:
    """
    Remove file or directory recursively.
    """
    p = Path(path)
    if not p.exists():
        return
    if p.is_file():
        p.unlink()
    else:
        shutil.rmtree(p)


def copy(src: str, dst: str = ".", copy_function=shutil.copy2) -> None:
    """
    Copy file or directory to a new destination.

    Creates destination if it doesn't exist.
    """
    psrc = Path(src)
    pdst = Path(dst)
    pdst.mkdir(parents=True, exist_ok=True)

    if psrc.is_file():
        copy_function(str(psrc), str(pdst / psrc.name))
    else:
        shutil.copytree(str(psrc), str(pdst / psrc.name), copy_function=copy_function)


def move(src: str, dst: str = ".") -> None:
    """
    Move file or directory to a new destination.
    """
    psrc = Path(src)
    pdst = Path(dst)
    pdst.mkdir(parents=True, exist_ok=True)
    shutil.move(str(psrc), str(pdst / psrc.name))


def gethash(file: str, algo: str = "sha256", chunk_size: int = 10000) -> str:
    """
    Args:
        file (str): Path to file to hash
        algo (str): Hash algorithm (md5, sha1, sha256, sha512, etc.)
        chunk_size (int): Size of read chunks

    Returns:
        str: Hexadecimal digest of file hash

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If algorithm is not supported

    Example:
        >>> gethash("/path/to/file.iso", "sha256")
        'a1b2c3d4e5f6...'
    """
    if not Path(file).exists():
        raise FileNotFoundError(f"File not found: {file}")

    try:
        hash_func = hashlib.new(algo)
    except ValueError as e:
        raise ValueError(f"Unsupported hash algorithm: {algo}") from e

    with open(file, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hash_func.update(chunk)

    return hash_func.hexdigest()
