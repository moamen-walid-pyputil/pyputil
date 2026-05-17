#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Platform detection and information gathering.

This module detects the current platform (Windows, Linux, macOS, etc.)
and gathers detailed system information for accurate package detection.
"""

import sys
import os
import platform
import subprocess
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

from .exceptions import PlatformDetectionError
from .utils import error_handler, platform_utils, safe_path
from .constants import PlatformType


@dataclass
class PlatformInfo:
    """Detailed platform information."""

    platform_type: PlatformType
    """Type of platform (Windows, Linux, macOS, etc.)."""

    system: str
    """System name (e.g., 'Linux', 'Windows', 'Darwin')."""

    release: str
    """System release version."""

    version: str
    """System version string."""

    machine: str
    """Machine architecture."""

    processor: str
    """Processor type."""

    is_64bit: bool
    """Whether running 64-bit Python."""

    python_version: str
    """Python version string."""

    python_implementation: str
    """Python implementation (CPython, PyPy, etc.)."""

    python_executable: Path
    """Path to Python executable."""

    is_virtual_machine: bool = False
    """Whether running in a virtual machine."""

    is_container: bool = False
    """Whether running in a container (Docker, etc.)."""

    is_wsl: bool = False
    """Whether running in Windows Subsystem for Linux."""

    wsl_version: Optional[int] = None
    """WSL version if running in WSL."""

    linux_distro: Optional[str] = None
    """Linux distribution name if applicable."""

    macos_version: Optional[Tuple[int, int, int]] = None
    """macOS version tuple if applicable."""

    windows_version: Optional[Tuple[int, int, int]] = None
    """Windows version tuple if applicable."""

    additional_info: Dict[str, Any] = None
    """Additional platform-specific information."""

    def __post_init__(self):
        if self.additional_info is None:
            self.additional_info = {}


class PlatformDetector:
    """Main platform detection class."""

    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._platform_info: Optional[PlatformInfo] = None

    @property
    def platform_info(self) -> PlatformInfo:
        """Get platform information (cached)."""
        if self._platform_info is None:
            self._platform_info = self._detect_platform()
        return self._platform_info

    def _detect_platform(self) -> PlatformInfo:
        """
        Detect and gather comprehensive platform information.

        Returns:
            PlatformInfo object with all platform details.

        Raises:
            PlatformDetectionError: If platform detection fails.
        """
        try:
            # Basic platform info from Python's platform module
            system = platform.system()
            release = platform.release()
            version = platform.version()
            machine = platform.machine()
            processor = platform.processor()

            # Detect platform type
            platform_type = self._detect_platform_type(system)

            # Check if running in virtual machine or container
            is_virtual_machine = self._check_virtual_machine()
            is_container = self._check_container()
            is_wsl = self._check_wsl()

            # Platform-specific information
            linux_distro = None
            macos_version = None
            windows_version = None
            wsl_version = None

            if platform_type == PlatformType.LINUX:
                linux_distro = self._detect_linux_distro()
                if is_wsl:
                    wsl_version = self._detect_wsl_version()
            elif platform_type == PlatformType.MACOS:
                macos_version = self._get_macos_version()
            elif platform_type == PlatformType.WINDOWS:
                windows_version = self._get_windows_version()

            return PlatformInfo(
                platform_type=platform_type,
                system=system,
                release=release,
                version=version,
                machine=machine,
                processor=processor,
                is_64bit=sys.maxsize > 2**32,
                python_version=platform.python_version(),
                python_implementation=platform.python_implementation(),
                python_executable=Path(sys.executable),
                is_virtual_machine=is_virtual_machine,
                is_container=is_container,
                is_wsl=is_wsl,
                wsl_version=wsl_version,
                linux_distro=linux_distro,
                macos_version=macos_version,
                windows_version=windows_version,
                additional_info=self._gather_additional_info(),
            )

        except Exception as e:
            raise PlatformDetectionError(e) from e

    def _detect_platform_type(self, system: str) -> PlatformType:
        """Detect platform type from system string."""
        system_lower = system.lower()

        if system_lower == "windows":
            return PlatformType.WINDOWS
        elif system_lower == "darwin":
            return PlatformType.MACOS
        elif system_lower == "linux":
            # Check for WSL
            if self._check_wsl():
                return PlatformType.WSL
            return PlatformType.LINUX
        elif "cygwin" in system_lower:
            return PlatformType.CYGWIN
        else:
            return PlatformType.UNKNOWN

    def _check_wsl(self) -> bool:
        """Check if running in Windows Subsystem for Linux."""
        try:
            # Check WSL-specific files
            wsl_files = ["/proc/version", "/proc/sys/kernel/osrelease"]

            for wsl_file in wsl_files:
                content = file_utils.read_text_safe(wsl_file)
                if content and (
                    "microsoft" in content.lower() or "wsl" in content.lower()
                ):
                    return True

            # Check environment variable
            if os.environ.get("WSL_DISTRO_NAME"):
                return True

        except Exception:
            pass

        return False

    def _detect_wsl_version(self) -> Optional[int]:
        """Detect WSL version."""
        try:
            content = file_utils.read_text_safe("/proc/version")
            if content:
                if "wsl2" in content.lower():
                    return 2
                elif "wsl" in content.lower():
                    return 1
        except Exception:
            pass

        return None

    def _check_virtual_machine(self) -> bool:
        """Check if running in a virtual machine."""
        try:
            # Common VM indicators
            vm_indicators = [
                # Hyper-V
                "/sys/class/dmi/id/product_name",
                "/sys/class/dmi/id/sys_vendor",
                # VMware
                "/sys/class/dmi/id/product_serial",
                # VirtualBox
                "/proc/scsi/scsi",
            ]

            for indicator in vm_indicators:
                content = file_utils.read_text_safe(indicator)
                if content:
                    content_lower = content.lower()
                    vm_keywords = ["virtual", "vmware", "vbox", "qemu", "kvm", "xen"]
                    if any(keyword in content_lower for keyword in vm_keywords):
                        return True

            # Check systemd-detect-virt if available
            try:
                result = subprocess.run(
                    ["systemd-detect-virt"], capture_output=True, text=True, timeout=2
                )
                if result.returncode == 0 and result.stdout.strip() not in ("none", ""):
                    return True
            except (subprocess.SubprocessError, FileNotFoundError):
                pass

        except Exception:
            pass

        return False

    def _check_container(self) -> bool:
        """Check if running in a container."""
        try:
            # Docker container check
            if os.path.exists("/.dockerenv"):
                return True

            # Check cgroups
            cgroup_content = file_utils.read_text_safe("/proc/1/cgroup")
            if cgroup_content:
                container_indicators = ["docker", "kubepods", "containerd", "crio"]
                if any(
                    indicator in cgroup_content for indicator in container_indicators
                ):
                    return True

            # Check for container runtime
            if os.environ.get("CONTAINER"):
                return True

        except Exception:
            pass

        return False

    def _detect_linux_distro(self) -> Optional[str]:
        """Detect Linux distribution."""
        try:
            # Try /etc/os-release first
            os_release = self._parse_os_release()
            if os_release and "NAME" in os_release:
                return os_release["NAME"]

            # Try legacy /etc/issue
            issue_content = file_utils.read_text_safe("/etc/issue")
            if issue_content:
                # Extract distribution name
                lines = issue_content.split("\n")
                if lines:
                    return lines[0].strip()

        except Exception:
            pass

        return None

    def _parse_os_release(self) -> Optional[Dict[str, str]]:
        """Parse /etc/os-release file."""
        try:
            content = file_utils.read_text_safe("/etc/os-release")
            if not content:
                return None

            result = {}
            for line in content.split("\n"):
                line = line.strip()
                if line and not line.startswith("#"):
                    if "=" in line:
                        key, value = line.split("=", 1)
                        # Remove quotes from value
                        value = value.strip("\"'")
                        result[key] = value

            return result
        except Exception:
            return None

    def _get_macos_version(self) -> Optional[Tuple[int, int, int]]:
        """Get macOS version."""
        try:
            mac_version = platform.mac_ver()[0]
            if mac_version:
                parts = mac_version.split(".")
                return tuple(map(int, parts[:3]))
        except (ValueError, IndexError):
            pass

        return None

    def _get_windows_version(self) -> Optional[Tuple[int, int, int]]:
        """Get Windows version."""
        try:
            win_version = platform.win32_ver()
            if win_version and len(win_version) >= 1:
                version_str = win_version[0]
                parts = version_str.split(".")
                return tuple(map(int, parts[:3]))
        except (ValueError, IndexError, AttributeError):
            pass

        return None

    def _gather_additional_info(self) -> Dict[str, Any]:
        """Gather additional platform-specific information."""
        info = {}

        try:
            # Get environment variables that might be useful
            env_vars = [
                "PATH",
                "HOME",
                "USER",
                "SHELL",
                "TERM",
                "LANG",
                "LC_ALL",
                "PYTHONPATH",
                "VIRTUAL_ENV",
                "CONDA_PREFIX",
                "PIPENV_ACTIVE",
            ]

            env_info = {}
            for var in env_vars:
                if var in os.environ:
                    env_info[var] = os.environ[var]

            if env_info:
                info["environment_variables"] = env_info

            # Get available memory
            try:
                import psutil

                memory = psutil.virtual_memory()
                info["memory"] = {
                    "total": memory.total,
                    "available": memory.available,
                    "percent": memory.percent,
                }
            except ImportError:
                pass

            # Get CPU count
            info["cpu_count"] = os.cpu_count()

        except Exception:
            # Silently ignore additional info errors
            pass

        return info

    def get_site_packages_paths(self) -> List[Path]:
        """
        Get all possible site-packages paths for the current platform.

        Returns:
            List of paths to site-packages directories.
        """
        cache_key = "site_packages_paths"
        if cache_key in self._cache:
            return self._cache[cache_key]

        paths = []

        try:
            # Get paths from site module
            site_paths = self._get_site_paths()
            paths.extend(site_paths)

            # Platform-specific additional paths
            platform_paths = self._get_platform_specific_paths()
            paths.extend(platform_paths)

            # Remove duplicates while preserving order
            unique_paths = []
            seen = set()

            for path in paths:
                resolved = safe_path.resolve(path)
                if resolved and resolved not in seen:
                    seen.add(resolved)
                    unique_paths.append(resolved)

            self._cache[cache_key] = unique_paths
            return unique_paths

        except Exception as e:
            warnings.warn(f"Failed to get site packages paths: {e}", RuntimeWarning)
            return []

    def _get_site_paths(self) -> List[Path]:
        """Get site paths from Python's site module."""
        paths = []

        try:
            # System site packages
            for sp in site.getsitepackages():
                paths.append(Path(sp))
        except AttributeError:
            pass

        try:
            # User site packages
            user_site = site.getusersitepackages()
            if user_site:
                paths.append(Path(user_site))
        except AttributeError:
            pass

        # Add from sys.path
        for path_str in sys.path:
            if path_str and (
                "site-packages" in path_str or "dist-packages" in path_str
            ):
                path = Path(path_str)
                if path.exists():
                    paths.append(path)

        return paths

    def _get_platform_specific_paths(self) -> List[Path]:
        """Get platform-specific package paths."""
        platform_type = self.platform_info.platform_type
        paths = []

        if platform_type == PlatformType.WINDOWS:
            # Windows-specific paths
            windows_paths = [
                Path.home() / "AppData" / "Roaming" / "Python",
                Path.home() / "AppData" / "Local" / "Programs" / "Python",
                Path("C:\\Python*"),
                Path(os.environ.get("PROGRAMFILES", "")) / "Python",
                Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Python",
            ]
            paths.extend(windows_paths)

        elif platform_type in (PlatformType.LINUX, PlatformType.WSL):
            # Linux-specific paths
            linux_paths = [
                Path.home() / ".local" / "lib",
                Path("/usr/local/lib"),
                Path("/usr/lib"),
                Path("/opt"),
                Path("/var/lib"),
            ]
            paths.extend(linux_paths)

        elif platform_type == PlatformType.MACOS:
            # macOS-specific paths
            macos_paths = [
                Path.home() / "Library" / "Python",
                Path("/Library/Python"),
                Path("/usr/local/lib"),
                Path("/opt/homebrew/lib"),  # Homebrew on Apple Silicon
                Path("/usr/local/opt"),  # Homebrew on Intel
            ]
            paths.extend(macos_paths)

        # Expand glob patterns
        expanded_paths = []
        for path in paths:
            if "*" in str(path):
                # Handle glob patterns
                try:
                    parent = path.parent
                    pattern = path.name
                    if parent.exists():
                        for matched in parent.glob(pattern):
                            expanded_paths.append(matched)
                except Exception:
                    pass
            else:
                expanded_paths.append(path)

        return expanded_paths

    def is_conda_environment(self) -> bool:
        """Check if running in a Conda environment."""
        try:
            return (
                "CONDA_PREFIX" in os.environ
                or "CONDA_DEFAULT_ENV" in os.environ
                or (Path(sys.prefix) / "conda-meta").exists()
            )
        except Exception:
            return False

    def is_venv_environment(self) -> bool:
        """Check if running in a virtual environment."""
        try:
            return (
                hasattr(sys, "real_prefix")
                or (sys.prefix != sys.base_prefix)
                or "VIRTUAL_ENV" in os.environ
            )
        except Exception:
            return False

    def get_environment_type(self) -> str:
        """Get the type of Python environment."""
        if self.is_conda_environment():
            return "conda"
        elif self.is_venv_environment():
            return "venv"
        else:
            return "system"


# Global platform detector instance
platform_detector = PlatformDetector()
