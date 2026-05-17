#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Environment detection and analysis.

This module detects and analyzes the Python environment including
virtual environments, Conda environments, Docker containers, and more.
"""

import os
import sys
import platform
import subprocess
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

from .exceptions import EnvironmentDetectionError
from .utils import error_handler, file_utils, safe_path, platform_utils
from .constants import EnvironmentType, PlatformType


@dataclass
class EnvironmentInfo:
    """Detailed environment information."""

    environment_type: EnvironmentType
    """Type of environment."""

    is_isolated: bool
    """Whether environment is isolated."""

    base_prefix: Path
    """Base Python installation prefix."""

    real_prefix: Optional[Path]
    """Real prefix (for virtual environments)."""

    prefix: Path
    """Current Python prefix."""

    path: Path
    """Path to environment."""

    python_version: str
    """Python version."""

    python_executable: Path
    """Path to Python executable."""

    is_64bit: bool
    """Whether running 64-bit Python."""

    # Specific environment info
    conda_info: Optional[Dict[str, Any]] = None
    """Conda-specific information."""

    venv_info: Optional[Dict[str, Any]] = None
    """Virtual environment information."""

    docker_info: Optional[Dict[str, Any]] = None
    """Docker-specific information."""

    system_info: Optional[Dict[str, Any]] = None
    """System-specific information."""

    additional_info: Dict[str, Any] = None
    """Additional environment information."""

    def __post_init__(self):
        if self.additional_info is None:
            self.additional_info = {}


class EnvironmentDetector:
    """Environment detection and analysis."""

    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._environment_info: Optional[EnvironmentInfo] = None

    @property
    def environment_info(self) -> EnvironmentInfo:
        """Get environment information (cached)."""
        if self._environment_info is None:
            self._environment_info = self._detect_environment()
        return self._environment_info

    def _detect_environment(self) -> EnvironmentInfo:
        """
        Detect and analyze the current environment.

        Returns:
            EnvironmentInfo object with detailed environment information.

        Raises:
            EnvironmentDetectionError: If environment detection fails.
        """
        try:
            # Basic environment information
            python_version = platform.python_version()
            python_executable = Path(sys.executable)
            prefix = Path(sys.prefix)
            base_prefix = Path(getattr(sys, "base_prefix", sys.prefix))
            real_prefix = (
                Path(getattr(sys, "real_prefix", None))
                if hasattr(sys, "real_prefix")
                else None
            )

            # Determine environment type
            env_type, env_path = self._determine_environment_type()
            is_isolated = self._check_is_isolated()

            # Gather environment-specific information
            conda_info = (
                self._get_conda_info() if env_type == EnvironmentType.CONDA else None
            )
            venv_info = (
                self._get_venv_info() if env_type == EnvironmentType.VENV else None
            )
            docker_info = self._get_docker_info()
            system_info = self._get_system_info()

            return EnvironmentInfo(
                environment_type=env_type,
                is_isolated=is_isolated,
                base_prefix=base_prefix,
                real_prefix=real_prefix,
                prefix=prefix,
                path=env_path,
                python_version=python_version,
                python_executable=python_executable,
                is_64bit=sys.maxsize > 2**32,
                conda_info=conda_info,
                venv_info=venv_info,
                docker_info=docker_info,
                system_info=system_info,
                additional_info=self._gather_additional_info(),
            )

        except Exception as e:
            raise EnvironmentDetectionError(e) from e

    def _determine_environment_type(self) -> Tuple[EnvironmentType, Optional[Path]]:
        """Determine the type of Python environment."""

        # Check for Conda first
        if self._is_conda_environment():
            conda_prefix = os.environ.get("CONDA_PREFIX")
            env_path = Path(conda_prefix) if conda_prefix else Path(sys.prefix)
            return EnvironmentType.CONDA, env_path

        # Check for virtual environment
        if self._is_virtual_environment():
            venv_path = os.environ.get("VIRTUAL_ENV")
            env_path = Path(venv_path) if venv_path else Path(sys.prefix)
            return EnvironmentType.VENV, env_path

        # Check for pipenv
        if "PIPENV_ACTIVE" in os.environ and os.environ["PIPENV_ACTIVE"] == "1":
            pipenv_project = os.environ.get("PIPENV_PROJECT")
            env_path = Path(pipenv_project) if pipenv_project else Path(sys.prefix)
            return EnvironmentType.PIPENV, env_path

        # Check for Poetry
        if "POETRY_ACTIVE" in os.environ and os.environ["POETRY_ACTIVE"] == "1":
            poetry_virtualenv = os.environ.get("POETRY_VIRTUALENV_PATH")
            env_path = (
                Path(poetry_virtualenv) if poetry_virtualenv else Path(sys.prefix)
            )
            return EnvironmentType.POETRY, env_path

        # Check for Docker
        if self._is_docker_container():
            return EnvironmentType.DOCKER, Path("/")

        # Default to system
        return EnvironmentType.SYSTEM, Path(sys.prefix)

    def _is_conda_environment(self) -> bool:
        """Check if running in a Conda environment."""
        try:
            # Check environment variables
            if "CONDA_PREFIX" in os.environ:
                return True

            if "CONDA_DEFAULT_ENV" in os.environ:
                return True

            # Check for conda-meta directory
            conda_meta = Path(sys.prefix) / "conda-meta"
            if conda_meta.exists() and conda_meta.is_dir():
                return True

            # Check Python executable path
            python_path = Path(sys.executable)
            if (
                "conda" in str(python_path).lower()
                or "anaconda" in str(python_path).lower()
            ):
                return True

            # Try to run conda command
            try:
                result = subprocess.run(
                    ["conda", "info", "--json"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                return result.returncode == 0
            except (subprocess.SubprocessError, FileNotFoundError):
                pass

            return False

        except Exception:
            return False

    def _is_virtual_environment(self) -> bool:
        """Check if running in a virtual environment."""
        try:
            # Check for VIRTUAL_ENV environment variable
            if "VIRTUAL_ENV" in os.environ:
                return True

            # Check Python attributes
            if hasattr(sys, "real_prefix"):
                return True

            if sys.prefix != sys.base_prefix:
                return True

            # Check for common venv files
            venv_files = ["pyvenv.cfg", "activate", "activate.bat"]
            for venv_file in venv_files:
                venv_path = Path(sys.prefix) / venv_file
                if venv_path.exists():
                    return True

            # Check for virtualenv indicator files
            virtualenv_files = ["lib", "include", "bin", "Scripts"]
            has_virtualenv_structure = all(
                (Path(sys.prefix) / dir_name).exists()
                for dir_name in virtualenv_files[:2]
            )

            if has_virtualenv_structure:
                return True

            return False

        except Exception:
            return False

    def _is_docker_container(self) -> bool:
        """Check if running in a Docker container."""
        try:
            # Check /.dockerenv file
            if Path("/.dockerenv").exists():
                return True

            # Check cgroup
            cgroup_content = file_utils.read_text_safe("/proc/1/cgroup")
            if cgroup_content:
                container_indicators = ["docker", "kubepods", "containerd", "crio"]
                if any(
                    indicator in cgroup_content for indicator in container_indicators
                ):
                    return True

            # Check environment variables
            if os.environ.get("container") == "docker":
                return True

            return False

        except Exception:
            return False

    def _check_is_isolated(self) -> bool:
        """Check if environment is isolated."""
        try:
            # Check for isolated build environment
            if "PYTHONNOUSERSITE" in os.environ:
                return True

            if "PYTHONISOLATED" in os.environ:
                return True

            # Check if running in a venv or conda env
            env_type = self._determine_environment_type()[0]
            if env_type in (
                EnvironmentType.VENV,
                EnvironmentType.CONDA,
                EnvironmentType.PIPENV,
                EnvironmentType.POETRY,
            ):
                return True

            return False

        except Exception:
            return False

    def _get_conda_info(self) -> Dict[str, Any]:
        """Get Conda-specific information."""
        info = {}

        try:
            # Get Conda environment variables
            env_vars = [
                "CONDA_PREFIX",
                "CONDA_DEFAULT_ENV",
                "CONDA_SHLVL",
                "CONDA_PROMPT_MODIFIER",
                "CONDA_EXE",
            ]

            for var in env_vars:
                if var in os.environ:
                    info[var.lower()] = os.environ[var]

            # Try to get conda info via command
            try:
                result = subprocess.run(
                    ["conda", "info", "--json"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )

                if result.returncode == 0:
                    import json

                    conda_data = json.loads(result.stdout)

                    # Extract useful information
                    useful_keys = ["conda_version", "platform", "envs", "envs_dirs"]
                    for key in useful_keys:
                        if key in conda_data:
                            info[key] = conda_data[key]
            except (
                subprocess.SubprocessError,
                FileNotFoundError,
                json.JSONDecodeError,
            ):
                pass

            # Get conda-meta information
            conda_meta_dir = Path(sys.prefix) / "conda-meta"
            if conda_meta_dir.exists():
                info["conda_meta_dir"] = str(conda_meta_dir)

                # Count installed packages
                try:
                    package_files = list(conda_meta_dir.glob("*.json"))
                    info["conda_package_count"] = len(package_files)
                except Exception:
                    pass

        except Exception as e:
            warnings.warn(f"Failed to get Conda info: {e}", RuntimeWarning)

        return info

    def _get_venv_info(self) -> Dict[str, Any]:
        """Get virtual environment information."""
        info = {}

        try:
            # Get VIRTUAL_ENV path
            if "VIRTUAL_ENV" in os.environ:
                venv_path = Path(os.environ["VIRTUAL_ENV"])
                info["venv_path"] = str(venv_path)

                # Check for pyvenv.cfg
                pyvenv_cfg = venv_path / "pyvenv.cfg"
                if pyvenv_cfg.exists():
                    cfg_content = file_utils.read_text_safe(pyvenv_cfg)
                    if cfg_content:
                        # Parse simple key=value format
                        cfg_info = {}
                        for line in cfg_content.splitlines():
                            line = line.strip()
                            if "=" in line:
                                key, value = line.split("=", 1)
                                cfg_info[key.strip()] = value.strip()

                        if cfg_info:
                            info["pyvenv_cfg"] = cfg_info

            # Check for virtualenv version
            try:
                import virtualenv

                info["virtualenv_version"] = virtualenv.__version__
            except ImportError:
                pass

            # Check for venv module availability
            try:
                import venv

                info["has_venv_module"] = True
            except ImportError:
                info["has_venv_module"] = False

        except Exception as e:
            warnings.warn(f"Failed to get venv info: {e}", RuntimeWarning)

        return info

    def _get_docker_info(self) -> Optional[Dict[str, Any]]:
        """Get Docker container information."""
        if not self._is_docker_container():
            return None

        info = {}

        try:
            # Read Docker container ID from cgroup
            cgroup_content = file_utils.read_text_safe("/proc/1/cgroup")
            if cgroup_content:
                # Try to extract container ID
                import re

                container_id_pattern = r"[0-9a-f]{64}"
                matches = re.findall(container_id_pattern, cgroup_content)
                if matches:
                    info["container_id"] = matches[0]

            # Check for Docker environment variables
            docker_env_vars = ["DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"]
            for var in docker_env_vars:
                if var in os.environ:
                    info[var.lower()] = os.environ[var]

            # Try to read /etc/hostname for container hostname
            hostname_content = file_utils.read_text_safe("/etc/hostname")
            if hostname_content:
                info["container_hostname"] = hostname_content.strip()

            # Check if running in Docker Compose
            if "COMPOSE_PROJECT_NAME" in os.environ:
                info["docker_compose"] = True
                info["compose_project"] = os.environ["COMPOSE_PROJECT_NAME"]

        except Exception as e:
            warnings.warn(f"Failed to get Docker info: {e}", RuntimeWarning)

        return info

    def _get_system_info(self) -> Dict[str, Any]:
        """Get system-specific information."""
        info = {}

        try:
            # Get platform information
            info["platform"] = platform.platform()
            info["system"] = platform.system()
            info["release"] = platform.release()
            info["machine"] = platform.machine()
            info["processor"] = platform.processor()

            # Get Python build information
            info["python_build"] = platform.python_build()
            info["python_compiler"] = platform.python_compiler()

            # Get system path information
            info["sys_prefix"] = sys.prefix
            info["sys_exec_prefix"] = sys.exec_prefix
            info["sys_base_prefix"] = getattr(sys, "base_prefix", sys.prefix)

            # Get path information
            info["sys_path"] = sys.path
            info["sys_executable"] = sys.executable

        except Exception as e:
            warnings.warn(f"Failed to get system info: {e}", RuntimeWarning)

        return info

    def _gather_additional_info(self) -> Dict[str, Any]:
        """Gather additional environment information."""
        info = {}

        try:
            # Get site-packages paths
            try:
                import site

                info["site_packages"] = site.getsitepackages()
                info["user_site"] = site.getusersitepackages()
            except AttributeError:
                pass

            # Get environment variables that might be useful
            useful_env_vars = [
                "PATH",
                "PYTHONPATH",
                "PYTHONHOME",
                "PYTHONSTARTUP",
                "PYTHONINSPECT",
                "PYTHONUNBUFFERED",
                "PYTHONVERBOSE",
                "PYTHONWARNINGS",
                "PYTHONOPTIMIZE",
                "PYTHONDEBUG",
            ]

            env_info = {}
            for var in useful_env_vars:
                if var in os.environ:
                    env_info[var] = os.environ[var]

            if env_info:
                info["python_env_vars"] = env_info

            # Get pip information if available
            try:
                import pip

                info["pip_version"] = pip.__version__
            except ImportError:
                pass

            # Get setuptools information if available
            try:
                import setuptools

                info["setuptools_version"] = setuptools.__version__
            except ImportError:
                pass

        except Exception as e:
            warnings.warn(f"Failed to gather additional info: {e}", RuntimeWarning)

        return info

    def get_package_locations(self) -> Dict[str, List[Path]]:
        """
        Get package installation locations for the current environment.

        Returns:
            Dictionary mapping location types to lists of paths.
        """
        locations = {
            "site_packages": [],
            "dist_packages": [],
            "user_site": [],
            "system": [],
            "other": [],
        }

        try:
            # Get from site module
            try:
                import site

                # System site packages
                for sp in site.getsitepackages():
                    locations["site_packages"].append(Path(sp))

                # User site packages
                user_site = site.getusersitepackages()
                if user_site:
                    locations["user_site"].append(Path(user_site))
            except AttributeError:
                pass

            # Check sys.path
            for path_str in sys.path:
                if not path_str:
                    continue

                path = Path(path_str)
                if not path.exists():
                    continue

                path_str_lower = str(path).lower()

                if "site-packages" in path_str_lower:
                    locations["site_packages"].append(path)
                elif "dist-packages" in path_str_lower:
                    locations["dist_packages"].append(path)
                elif "lib" in path_str_lower and "python" in path_str_lower:
                    locations["system"].append(path)
                else:
                    locations["other"].append(path)

            # Remove duplicates
            for key in locations:
                unique_paths = []
                seen = set()

                for path in locations[key]:
                    resolved = safe_path.resolve(path)
                    if resolved and resolved not in seen:
                        seen.add(resolved)
                        unique_paths.append(resolved)

                locations[key] = unique_paths

        except Exception as e:
            warnings.warn(f"Failed to get package locations: {e}", RuntimeWarning)

        return locations

    def is_editable_install(self, package_path: Path) -> bool:
        """
        Check if a package is installed in editable mode.

        Args:
            package_path: Path to the package.

        Returns:
            True if package is installed in editable mode.
        """
        try:
            # Check for .egg-link files
            for location_type, paths in self.get_package_locations().items():
                for location_path in paths:
                    # Look for .egg-link files
                    for egg_link in location_path.glob("*.egg-link"):
                        try:
                            with open(egg_link, "r") as f:
                                linked_path = Path(f.readline().strip())
                                if safe_path.is_relative_to(package_path, linked_path):
                                    return True
                        except Exception:
                            continue

            # Check for .pth files
            for location_type, paths in self.get_package_locations().items():
                for location_path in paths:
                    # Look for .pth files
                    for pth_file in location_path.glob("*.pth"):
                        try:
                            with open(pth_file, "r") as f:
                                for line in f:
                                    line = line.strip()
                                    if line and not line.startswith("#"):
                                        pth_path = Path(line)
                                        if safe_path.is_relative_to(
                                            package_path, pth_path
                                        ):
                                            return True
                        except Exception:
                            continue

            return False

        except Exception:
            return False


# Global environment detector instance
environment_detector = EnvironmentDetector()
