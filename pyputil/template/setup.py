#!/usr/bin/env python3

# -*- coding: utf-8 -*-

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Module for generating setup.py files with configuration.
"""

import os
import sys
import ast
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union, Any, Set, Tuple
from enum import Enum


class VersionSource(str, Enum):
    """Version source options."""
    STATIC = "static"
    FILE = "file"
    GIT = "git"
    INIT = "init"
    AUTO = "auto"


class BuildBackend(str, Enum):
    """Build backend options."""
    SETUPTOOLS = "setuptools"
    POETRY = "poetry"
    HATCH = "hatch"
    FLIT = "flit"
    PDM = "pdm"


class SetupGenerator:
    """
    Generator for setup.py files with comprehensive features.
    
    This class provides a modular approach to generating setup.py files
    with automatic dependency detection, version management, and
    best practices for Python packaging.
    """
    
    def __init__(self):
        """Initialize the setup generator."""
        self.metadata = {}
        self.dependencies = {}
        self.entry_points = {}
        self.classifiers = []
        self._version_source = VersionSource.AUTO
        
    def set_metadata(
        self,
        name: str,
        version: Optional[str] = None,
        description: Optional[str] = None,
        long_description: Optional[str] = None,
        author: Optional[str] = None,
        author_email: Optional[str] = None,
        url: Optional[str] = None,
        license_name: Optional[str] = None,
        python_requires: str = ">=3.8",
    ) -> 'SetupGenerator':
        """Set basic package metadata."""
        self.metadata.update({
            "name": name,
            "version": version,
            "description": description,
            "long_description": long_description,
            "author": author,
            "author_email": author_email,
            "url": url,
            "license": license_name,
            "python_requires": python_requires,
        })
        return self
    
    def set_version_source(
        self,
        source: VersionSource,
        file_path: Optional[str] = None,
        attr: Optional[str] = None
    ) -> 'SetupGenerator':
        """
        Configure how version is determined.
        
        Parameters
        ----------
        source : VersionSource
            Source of version information.
        file_path : str, optional
            Path to version file for VersionSource.FILE.
        attr : str, optional
            Attribute to read for VersionSource.INIT.
        """
        self._version_source = source
        self._version_file = file_path
        self._version_attr = attr
        return self
    
    def add_dependencies(
        self,
        install_requires: Optional[List[str]] = None,
        extras_require: Optional[Dict[str, List[str]]] = None,
        setup_requires: Optional[List[str]] = None,
        tests_require: Optional[List[str]] = None,
    ) -> 'SetupGenerator':
        """Add dependencies."""
        self.dependencies.update({
            "install_requires": install_requires or [],
            "extras_require": extras_require or {},
            "setup_requires": setup_requires or [],
            "tests_require": tests_require or [],
        })
        return self
    
    def add_entry_points(
        self,
        console_scripts: Optional[List[str]] = None,
        gui_scripts: Optional[List[str]] = None,
        **custom_groups: List[str]
    ) -> 'SetupGenerator':
        """Add entry points for console scripts and plugins."""
        self.entry_points = {}
        if console_scripts:
            self.entry_points["console_scripts"] = console_scripts
        if gui_scripts:
            self.entry_points["gui_scripts"] = gui_scripts
        for group, scripts in custom_groups.items():
            self.entry_points[group] = scripts
        return self
    
    def add_classifiers(self, classifiers: List[str]) -> 'SetupGenerator':
        """Add PyPI classifiers."""
        self.classifiers.extend(classifiers)
        return self
    
    def auto_detect_from_package(
        self,
        package_path: Union[str, Path],
        scan_imports: bool = True,
        detect_version: bool = True
    ) -> 'SetupGenerator':
        """
        Auto-detect package structure and metadata.
        
        Parameters
        ----------
        package_path : str or Path
            Path to the package root.
        scan_imports : bool, default=True
            Scan Python files for imports to detect dependencies.
        detect_version : bool, default=True
            Try to detect version from __init__.py or VERSION file.
        """
        pkg_path = Path(package_path).resolve()
        
        if not pkg_path.exists():
            raise FileNotFoundError(f"Package path not found: {pkg_path}")
        
        # Detect packages
        packages = self._detect_packages(pkg_path)
        if packages:
            self.metadata["packages"] = packages
            self.metadata["package_dir"] = {"": str(pkg_path.parent)}
        
        # Detect name from package structure
        if "name" not in self.metadata and packages:
            self.metadata["name"] = packages[0]
        
        # Detect long description from README
        if "long_description" not in self.metadata:
            self.metadata["long_description"] = self._get_long_description(pkg_path)
        
        # Detect version
        if detect_version and self._version_source == VersionSource.AUTO:
            self._auto_detect_version(pkg_path)
        
        # Detect dependencies from imports
        if scan_imports and not self.dependencies.get("install_requires"):
            imports = self._scan_imports(pkg_path)
            self.dependencies["install_requires"] = self._filter_stdlib(imports)
        
        return self
    
    def build(self, output_dir: Union[str, Path] = ".", force: bool = False) -> Path:
        """
        Generate the setup.py file.
        
        Parameters
        ----------
        output_dir : str or Path, default="."
            Directory to write setup.py.
        force : bool, default=False
            Overwrite existing setup.py.
            
        Returns
        -------
        Path
            Path to the generated setup.py file.
        """
        output_path = Path(output_dir).resolve()
        output_path.mkdir(parents=True, exist_ok=True)
        
        setup_file = output_path / "setup.py"
        
        if setup_file.exists() and not force:
            raise FileExistsError(
                f"{setup_file} already exists. Use force=True to overwrite."
            )
        
        content = self._generate_content()
        setup_file.write_text(content, encoding="utf-8")
        setup_file.chmod(0o755)
        
        return setup_file
    
    def _generate_content(self) -> str:
        """Generate the complete setup.py content."""
        # Get version string based on source
        version_code = self._get_version_code()
        
        # Format lists and dicts
        install_requires = self._format_list(self.dependencies.get("install_requires", []))
        extras_require = self._format_dict(self.dependencies.get("extras_require", {}))
        entry_points = self._format_entry_points(self.entry_points)
        classifiers = self._format_list(self._get_full_classifiers())
        
        # Generate template
        return f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Setup configuration for {self.metadata.get('name', 'unknown')}.

Generated by setup_template on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

import os
import sys
from setuptools import setup, find_packages


{version_code}


def read_readme() -> str:
    \"\"\"Read the README file if it exists.\"\"\"
    readme_files = ['README.md', 'README.rst', 'README.txt']
    for readme_file in readme_files:
        if os.path.exists(readme_file):
            with open(readme_file, 'r', encoding='utf-8') as f:
                return f.read()
    return {repr(self.metadata.get('long_description', ''))}


# Package metadata
PACKAGE_NAME = {repr(self.metadata.get('name', 'unknown'))}
VERSION = get_version()
DESCRIPTION = {repr(self.metadata.get('description', ''))}
LONG_DESCRIPTION = read_readme()
AUTHOR = {repr(self.metadata.get('author', ''))}
AUTHOR_EMAIL = {repr(self.metadata.get('author_email', ''))}
URL = {repr(self.metadata.get('url', ''))}
LICENSE = {repr(self.metadata.get('license', 'MIT'))}
PYTHON_REQUIRES = {repr(self.metadata.get('python_requires', '>=3.8'))}

# Dependencies
INSTALL_REQUIRES = {install_requires}
EXTRAS_REQUIRE = {extras_require}
SETUP_REQUIRES = {self._format_list(self.dependencies.get('setup_requires', []))}
TESTS_REQUIRE = {self._format_list(self.dependencies.get('tests_require', []))}

# Entry points
ENTRY_POINTS = {entry_points}

# Classifiers
CLASSIFIERS = {classifiers}

if __name__ == '__main__':
    setup(
        name=PACKAGE_NAME,
        version=VERSION,
        description=DESCRIPTION,
        long_description=LONG_DESCRIPTION,
        long_description_content_type={repr(self.metadata.get('long_description_content_type', 'text/markdown'))},
        author=AUTHOR,
        author_email=AUTHOR_EMAIL,
        url=URL,
        license=LICENSE,
        python_requires=PYTHON_REQUIRES,
        install_requires=INSTALL_REQUIRES,
        extras_require=EXTRAS_REQUIRE,
        setup_requires=SETUP_REQUIRES,
        tests_require=TESTS_REQUIRE,
        entry_points=ENTRY_POINTS,
        packages=find_packages() if not self.metadata.get('packages') else {repr(self.metadata.get('packages', []))},
        package_dir={repr(self.metadata.get('package_dir', {{}}))},
        include_package_data={repr(self.metadata.get('include_package_data', True))},
        zip_safe={repr(self.metadata.get('zip_safe', False))},
        classifiers=CLASSIFIERS,
        keywords={repr(self.metadata.get('keywords', []))},
        project_urls={repr(self.metadata.get('project_urls', {{}}))},
    )
'''
    
    def _get_version_code(self) -> str:
        """Generate version detection code."""
        if self._version_source == VersionSource.STATIC:
            version = self.metadata.get('version', '0.1.0')
            return f'''def get_version() -> str:
    \"\"\"Return package version.\"\"\"
    return {repr(version)}'''
        
        elif self._version_source == VersionSource.FILE:
            file_path = getattr(self, '_version_file', 'VERSION')
            return f'''def get_version() -> str:
    \"\"\"Read version from VERSION file.\"\"\"
    version_file = os.path.join(os.path.dirname(__file__), {repr(file_path)})
    if os.path.exists(version_file):
        with open(version_file, 'r') as f:
            return f.read().strip()
    return '0.1.0' '''
        
        elif self._version_source == VersionSource.GIT:
            return '''def get_version() -> str:
    \"\"\"Get version from git tags.\"\"\"
    try:
        import subprocess
        git_version = subprocess.check_output(
            ['git', 'describe', '--tags', '--dirty'],
            stderr=subprocess.DEVNULL
        ).decode().strip()
        if git_version:
            return git_version
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return '0.1.0' '''
        
        elif self._version_source == VersionSource.INIT:
            attr = getattr(self, '_version_attr', '__version__')
            return f'''def get_version() -> str:
    \"\"\"Read version from package __init__.py.\"\"\"
    import ast
    init_file = os.path.join(os.path.dirname(__file__), {repr(self.metadata.get('name', 'src'))}, '__init__.py')
    if os.path.exists(init_file):
        with open(init_file, 'r') as f:
            for line in f:
                if line.startswith('{attr}'):
                    return line.split('=')[1].strip().strip("'\\"")
    return '0.1.0' '''
        
        else:  # AUTO
            return '''def get_version() -> str:
    \"\"\"Auto-detect version from various sources.\"\"\"
    # Try VERSION file first
    version_file = os.path.join(os.path.dirname(__file__), 'VERSION')
    if os.path.exists(version_file):
        with open(version_file, 'r') as f:
            return f.read().strip()
    
    # Try git tags
    try:
        import subprocess
        git_version = subprocess.check_output(
            ['git', 'describe', '--tags', '--dirty'],
            stderr=subprocess.DEVNULL
        ).decode().strip()
        if git_version:
            return git_version
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    
    # Try __init__.py
    init_file = os.path.join(os.path.dirname(__file__), 'src', '__init__.py')
    if os.path.exists(init_file):
        import ast
        with open(init_file, 'r') as f:
            for line in f:
                if line.startswith('__version__'):
                    return line.split('=')[1].strip().strip("'\\"")
    
    return '0.1.0' '''
    
    @staticmethod
    def _detect_packages(package_path: Path) -> List[str]:
        """Auto-detect packages in directory."""
        packages = []
        for item in package_path.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                init_file = item / '__init__.py'
                if init_file.exists():
                    packages.append(item.name)
        return packages
    
    @staticmethod
    def _get_long_description(package_path: Path) -> str:
        """Read README file if exists."""
        for readme in ['README.md', 'README.rst', 'README.txt']:
            readme_path = package_path / readme
            if readme_path.exists():
                try:
                    return readme_path.read_text(encoding='utf-8')
                except (IOError, UnicodeDecodeError):
                    continue
        return ''
    
    @staticmethod
    def _scan_imports(package_path: Path) -> List[str]:
        """Scan Python files for import statements."""
        imports = set()
        
        for py_file in package_path.rglob('*.py'):
            try:
                content = py_file.read_text(encoding='utf-8')
                tree = ast.parse(content)
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imports.add(alias.name.split('.')[0])
                    elif isinstance(node, ast.ImportFrom):
                        if node.module and node.module != '__future__':
                            imports.add(node.module.split('.')[0])
            except (SyntaxError, UnicodeDecodeError):
                continue
        
        return sorted(imports)
    
    @staticmethod
    def _filter_stdlib(imports: List[str]) -> List[str]:
        """Filter out standard library imports."""
        from ..modules import is_stdlib  
        return [imp for imp in imports if not is_stdlib(imp)]
    
    def _auto_detect_version(self, package_path: Path):
        """Auto-detect version from various sources."""
        # Check VERSION file
        version_file = package_path / 'VERSION'
        if version_file.exists():
            try:
                version = version_file.read_text().strip()
                if re.match(r'^\d+\.\d+\.\d+', version):
                    self.metadata['version'] = version
                    self._version_source = VersionSource.FILE
                    self._version_file = 'VERSION'
                    return
            except IOError:
                pass
        
        # Check git tags
        try:
            git_version = subprocess.check_output(
                ['git', 'describe', '--tags', '--abbrev=0'],
                stderr=subprocess.DEVNULL,
                cwd=package_path
            ).decode().strip()
            if re.match(r'^v?\d+\.\d+\.\d+', git_version):
                self.metadata['version'] = git_version.lstrip('v')
                self._version_source = VersionSource.GIT
                return
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
        
        # Check __init__.py
        for init_path in package_path.rglob('__init__.py'):
            try:
                content = init_path.read_text(encoding='utf-8')
                match = re.search(r'__version__\s*=\s*[\'"]([^\'"]+)[\'"]', content)
                if match:
                    self.metadata['version'] = match.group(1)
                    self._version_source = VersionSource.INIT
                    self._version_attr = '__version__'
                    return
            except (IOError, UnicodeDecodeError):
                continue
    
    def _get_full_classifiers(self) -> List[str]:
        """Generate full classifier list with defaults."""
        classifiers = self.classifiers.copy()
        
        # Add default classifiers if not present
        if not any('Development Status' in c for c in classifiers):
            classifiers.append('Development Status :: 4 - Beta')
        
        if not any('Intended Audience' in c for c in classifiers):
            classifiers.append('Intended Audience :: Developers')
        
        if not any('Programming Language :: Python :: 3' in c for c in classifiers):
            classifiers.append('Programming Language :: Python :: 3')
            classifiers.append('Programming Language :: Python :: 3.8')
            classifiers.append('Programming Language :: Python :: 3.9')
            classifiers.append('Programming Language :: Python :: 3.10')
            classifiers.append('Programming Language :: Python :: 3.11')
            classifiers.append('Programming Language :: Python :: 3.12')
        
        if not any('License' in c for c in classifiers):
            license_name = self.metadata.get('license', 'MIT')
            license_map = {
                'MIT': 'License :: OSI Approved :: MIT License',
                'Apache': 'License :: OSI Approved :: Apache Software License',
                'GPL': 'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
                'BSD': 'License :: OSI Approved :: BSD License',
            }
            classifiers.append(license_map.get(license_name, f'License :: {license_name}'))
        
        return sorted(set(classifiers))
    
    @staticmethod
    def _format_list(items: List[Any]) -> str:
        """Format a list for setup.py."""
        if not items:
            return '[]'
        return f'[\n    {repr(items[0])},\n]' if len(items) == 1 else repr(items)
    
    @staticmethod
    def _format_dict(items: Dict[str, Any]) -> str:
        """Format a dictionary for setup.py."""
        if not items:
            return '{}'
        return repr(items)
    
    @staticmethod
    def _format_entry_points(entry_points: Dict[str, List[str]]) -> str:
        """Format entry points for setup.py."""
        if not entry_points:
            return '{}'
        
        formatted = {}
        for group, scripts in entry_points.items():
            if isinstance(scripts, list):
                formatted[group] = [s for s in scripts]
            else:
                formatted[group] = scripts
        
        return repr(formatted)


def setup_template(
    package_name: str,
    package_path: Optional[Union[str, Path]] = None,
    version: Optional[str] = None,
    description: Optional[str] = None,
    author: Optional[str] = None,
    author_email: Optional[str] = None,
    url: Optional[str] = None,
    license_name: str = "MIT",
    python_requires: str = ">=3.8",
    install_requires: Optional[List[str]] = None,
    extras_require: Optional[Dict[str, List[str]]] = None,
    entry_points: Optional[Dict[str, List[str]]] = None,
    classifiers: Optional[List[str]] = None,
    keywords: Optional[List[str]] = None,
    project_urls: Optional[Dict[str, str]] = None,
    version_source: VersionSource = VersionSource.AUTO,
    version_file: Optional[str] = None,
    version_attr: Optional[str] = None,
    include_package_data: bool = True,
    zip_safe: bool = False,
    long_description_content_type: str = "text/markdown",
    output_dir: Union[str, Path] = ".",
    force_overwrite: bool = False,
    auto_detect: bool = True,
    scan_imports: bool = True,
    build_requirements: bool = True,
) -> str:
    """
    Generate a professional setup.py file for a Python package.
    
    This function creates a comprehensive setup.py with automatic dependency
    detection, version management, and best practices for Python packaging.
    
    Parameters
    ----------
    package_name : str
        The name of the package (must be valid on PyPI).
    package_path : str or Path, optional
        Path to the package root directory. If not provided, uses current directory.
    version : str, optional
        Package version. If auto_detect is True, will try to detect from various sources.
    description : str, optional
        Short package description.
    author : str, optional
        Author name.
    author_email : str, optional
        Author email.
    url : str, optional
        Project homepage URL.
    license_name : str, default="MIT"
        License type (MIT, Apache, GPL, etc.).
    python_requires : str, default=">=3.8"
        Python version requirement.
    install_requires : list, optional
        List of package dependencies. If auto_detect is True, will scan imports.
    extras_require : dict, optional
        Optional dependencies for extra features.
    entry_points : dict, optional
        Console scripts and entry points.
    classifiers : list, optional
        PyPI classifiers. If not provided, will generate sensible defaults.
    keywords : list, optional
        Package keywords.
    project_urls : dict, optional
        Additional project URLs.
    version_source : VersionSource, default="auto"
        Source for version detection: static, file, git, init, auto.
    version_file : str, optional
        Path to version file for VersionSource.FILE.
    version_attr : str, optional
        Attribute name for VersionSource.INIT.
    include_package_data : bool, default=True
        Include package data files.
    zip_safe : bool, default=False
        Whether package is zip-safe.
    long_description_content_type : str, default="text/markdown"
        Content type for long description.
    output_dir : str or Path, default="."
        Directory to write setup.py.
    force_overwrite : bool, default=False
        Overwrite existing setup.py.
    auto_detect : bool, default=True
        Auto-detect package structure and metadata.
    scan_imports : bool, default=True
        Scan Python files for imports to detect dependencies.
    build_requirements : bool, default=True
        Build requirements.txt file automatically.
    
    Returns
    -------
    str
        Path to the generated setup.py file.
    
    Examples
    --------
    Basic usage:
    >>> setup_template(
    ...     package_name="mypackage",
    ...     version="1.0.0",
    ...     author="John Doe",
    ...     author_email="john@example.com"
    ... )
    
    Advanced usage with auto-detection:
    >>> setup_template(
    ...     package_name="mypackage",
    ...     package_path="./src/mypackage",
    ...     version_source=VersionSource.GIT,
    ...     entry_points={
    ...         "console_scripts": ["mycli = mypackage.cli:main"]
    ...     }
    ... )
    
    With extras:
    >>> setup_template(
    ...     package_name="mypackage",
    ...     install_requires=["requests>=2.28.0"],
    ...     extras_require={
    ...         "dev": ["pytest", "black"],
    ...         "ml": ["numpy", "pandas"]
    ...     }
    ... )
    
    Using git version:
    >>> setup_template(
    ...     package_name="mypackage",
    ...     version_source=VersionSource.GIT
    ... )
    
    Notes
    -----
    - Auto-detection scans for packages, README, and imports
    - Version detection works with VERSION file, git tags, and __init__.py
    - Generated setup.py includes comprehensive error handling
    - Requirements can be exported to requirements.txt
    - Supports all modern Python packaging standards
    """
    
    # Initialize generator
    generator = SetupGenerator()
    
    # Set package path
    if package_path is None:
        package_path = Path.cwd()
    else:
        package_path = Path(package_path).resolve()
    
    # Set metadata
    generator.set_metadata(
        name=package_name,
        version=version,
        description=description,
        author=author,
        author_email=author_email,
        url=url,
        license_name=license_name,
        python_requires=python_requires,
        long_description_content_type=long_description_content_type,
    )
    
    # Set version source
    if version_source != VersionSource.AUTO:
        generator.set_version_source(version_source, version_file, version_attr)
    
    # Add dependencies
    generator.add_dependencies(
        install_requires=install_requires,
        extras_require=extras_require,
    )
    
    # Add entry points
    if entry_points:
        for group, scripts in entry_points.items():
            if group == "console_scripts":
                generator.add_entry_points(console_scripts=scripts)
            else:
                generator.add_entry_points(**{group: scripts})
    
    # Add classifiers
    if classifiers:
        generator.add_classifiers(classifiers)
    
    # Store additional metadata
    generator.metadata["keywords"] = keywords or []
    generator.metadata["project_urls"] = project_urls or {}
    generator.metadata["include_package_data"] = include_package_data
    generator.metadata["zip_safe"] = zip_safe
    
    # Auto-detect from package
    if auto_detect and package_path.exists():
        generator.auto_detect_from_package(
            package_path,
            scan_imports=scan_imports,
            detect_version=version is None
        )
    
    # Build requirements.txt if requested
    if build_requirements and generator.dependencies.get("install_requires"):
        _build_requirements_txt(
            generator.dependencies["install_requires"],
            output_dir
        )
    
    # Generate setup.py
    setup_file = generator.build(output_dir, force=force_overwrite)
    
    return str(setup_file)


def _build_requirements_txt(dependencies: List[str], output_dir: Union[str, Path]) -> None:
    """Build requirements.txt file from dependencies."""
    req_file = Path(output_dir) / "requirements.txt"
    
    content = "# Generated from setup.py dependencies\n"
    content += "# Install with: pip install -r requirements.txt\n\n"
    content += "\n".join(sorted(dependencies))
    
    req_file.write_text(content, encoding="utf-8")


def write_setup(path: Union[str, Path] = "setup.py", **kwargs) -> None:
    """
    Generate setup.py and write it directly to disk.
    
    Parameters
    ----------
    path : str or Path, default="setup.py"
        Path where to write the setup.py file.
    **kwargs
        Additional arguments passed to setup_template().
        
    Examples
    --------
    >>> write_setup("setup.py", package_name="mypackage", version="1.0.0")
    """
    output_dir = Path(path).parent
    if not output_dir:
        output_dir = "."
    
    setup_template(output_dir=output_dir, **kwargs)
