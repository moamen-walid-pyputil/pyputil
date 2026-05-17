#!/usr/bin/env python3

# -*- coding: utf-8 -*-

from typing import Optional, List, Dict, Union, Literal
from datetime import datetime
from pathlib import Path
import re
from enum import Enum


class FeatureStyle(str, Enum):
    """Feature display style options."""
    LIST = "list"
    TABLE = "table"
    GRID = "grid"


class SectionVisibility(str, Enum):
    """Section visibility options."""
    AUTO = "auto"
    ALWAYS = "always"
    NEVER = "never"


class ReadmeBuilder:
    """
    A modular builder for generating README.md files.
    
    This class provides a flexible, component-based approach to building
    README files with proper structure, automatic TOC generation, and
    smart section management.
    """
    
    def __init__(self):
        """Initialize the README builder with empty sections."""
        self.sections = []
        self._toc_entries = []
        self._badges = []
        self._has_title = False
        
    def add_title(self, name: str, version: Optional[str] = None) -> 'ReadmeBuilder':
        """Add project title and header."""
        title_text = f"# {name}"
        if version:
            title_text += f" v{version}"
        self.sections.append(title_text)
        self._has_title = True
        return self
    
    def add_badges(self, badges: Dict[str, Union[str, Dict[str, str]]]) -> 'ReadmeBuilder':
        """
        Add badges with automatic shields.io support.
        
        Parameters
        ----------
        badges : dict
            Badge configurations. Can be:
            - Simple: {"python": "3.10"}
            - Advanced: {"coverage": {"label": "coverage", "value": "95%", "color": "green"}}
            - Custom URL: {"docs": "https://img.shields.io/badge/docs-latest-blue"}
        """
        badge_lines = []
        
        for name, config in badges.items():
            if isinstance(config, str):
                # Simple badge - use shields.io
                label = name.replace("_", "-").title()
                value = config
                color = self._get_badge_color(name, config)
                badge_url = f"https://img.shields.io/badge/{label}-{value}-{color}"
                badge_lines.append(f"![{name}]({badge_url})")
            elif isinstance(config, dict):
                # Advanced badge configuration
                label = config.get("label", name)
                value = config.get("value", "")
                color = config.get("color", "blue")
                if "url" in config:
                    badge_url = config["url"]
                else:
                    badge_url = f"https://img.shields.io/badge/{label}-{value}-{color}"
                badge_lines.append(f"![{name}]({badge_url})")
        
        if badge_lines:
            self.sections.append(" ".join(badge_lines))
        
        return self
    
    def add_toc(self, sections: Optional[List[str]] = None, min_sections: int = 4) -> 'ReadmeBuilder':
        """
        Add table of contents automatically.
        
        Parameters
        ----------
        sections : list, optional
            List of section names to include. If None, uses all sections.
        min_sections : int, default=4
            Minimum number of sections required to show TOC.
        """
        if sections is None:
            sections = self._toc_entries
        
        if len(sections) >= min_sections:
            toc_lines = ["## Table of Contents"]
            for section in sections:
                # Create anchor link (lowercase, replace spaces with hyphens)
                anchor = section.lower().replace(" ", "-").replace("_", "-")
                toc_lines.append(f"- [{section}](#{anchor})")
            self.sections.append("\n".join(toc_lines))
        
        return self
    
    def add_description(self, description: str, badges: Optional[Dict[str, str]] = None) -> 'ReadmeBuilder':
        """Add project description section."""
        self._toc_entries.append("Description")
        lines = ["## 📝 Description", "", description]
        self.sections.append("\n".join(lines))
        return self
    
    def add_installation(
        self,
        methods: Optional[Dict[str, str]] = None,
        requirements: Optional[List[str]] = None,
        python_version: Optional[str] = None
    ) -> 'ReadmeBuilder':
        """
        Add installation section with multiple methods.
        
        Parameters
        ----------
        methods : dict, optional
            Installation methods, e.g.:
            {
                "pip": "pip install mypackage",
                "poetry": "poetry add mypackage",
                "from source": "git clone https://github.com/..."
            }
        requirements : list, optional
            List of system requirements or prerequisites.
        python_version : str, optional
            Required Python version.
        """
        self._toc_entries.append("Installation")
        lines = ["## 🚀 Installation", ""]
        
        # Add requirements if provided
        if requirements or python_version:
            lines.append("### Requirements")
            if python_version:
                lines.append(f"- Python {python_version} or higher")
            if requirements:
                for req in requirements:
                    lines.append(f"- {req}")
            lines.append("")
        
        # Add installation methods
        if methods:
            lines.append("### Installation Methods")
            for method, command in methods.items():
                lines.append(f"**{method.title()}:**")
                lines.append("```bash")
                lines.append(command)
                lines.append("```")
                lines.append("")
        else:
            # Default installation
            lines.append("```bash")
            lines.append("pip install your-package-name")
            lines.append("```")
        
        self.sections.append("\n".join(lines))
        return self
    
    def add_usage(
        self,
        examples: Optional[Dict[str, str]] = None,
        code_block_lang: str = "python"
    ) -> 'ReadmeBuilder':
        """
        Add usage examples section.
        
        Parameters
        ----------
        examples : dict, optional
            Usage examples, e.g.:
            {
                "Basic": "import mypackage\nmypackage.do_something()",
                "Advanced": "from mypackage import Client\nclient = Client()"
            }
        code_block_lang : str, default="python"
            Language for code blocks.
        """
        self._toc_entries.append("Usage")
        lines = ["## 💻 Usage", ""]
        
        if examples:
            for title, code in examples.items():
                lines.append(f"### {title}")
                lines.append(f"```{code_block_lang}")
                lines.append(code.strip())
                lines.append("```")
                lines.append("")
        else:
            # Default usage
            lines.append("```python")
            lines.append("import your_package")
            lines.append("")
            lines.append("# Example usage")
            lines.append("your_package.do_something()")
            lines.append("```")
        
        self.sections.append("\n".join(lines))
        return self
    
    def add_features(
        self,
        features: Union[List[str], Dict[str, str]],
        style: FeatureStyle = FeatureStyle.LIST,
        columns: int = 3
    ) -> 'ReadmeBuilder':
        """
        Add features section.
        
        Parameters
        ----------
        features : list or dict
            List of features or dict with descriptions.
        style : FeatureStyle, default="list"
            Display style: "list", "table", or "grid".
        columns : int, default=3
            Number of columns for grid style.
        """
        self._toc_entries.append("Features")
        lines = ["## ✨ Features", ""]
        
        if style == FeatureStyle.LIST:
            if isinstance(features, dict):
                for feature, desc in features.items():
                    lines.append(f"- **{feature}**: {desc}")
            else:
                for feature in features:
                    lines.append(f"- {feature}")
        
        elif style == FeatureStyle.TABLE:
            lines.append("| Feature | Description |")
            lines.append("|---------|-------------|")
            if isinstance(features, dict):
                for feature, desc in features.items():
                    lines.append(f"| **{feature}** | {desc} |")
            else:
                for feature in features:
                    lines.append(f"| {feature} | - |")
        
        elif style == FeatureStyle.GRID:
            # Create grid layout using HTML table
            lines.append('<div style="display: grid; grid-template-columns: repeat({}, 1fr); gap: 20px;">'.format(columns))
            if isinstance(features, dict):
                items = list(features.items())
            else:
                items = [(f, "") for f in features]
            
            for feature, desc in items:
                lines.append('  <div style="padding: 15px; border: 1px solid #ddd; border-radius: 5px;">')
                lines.append(f'    <strong>{feature}</strong>')
                if desc:
                    lines.append(f'    <p style="margin-top: 10px;">{desc}</p>')
                lines.append("  </div>")
            lines.append("</div>")
        
        self.sections.append("\n".join(lines))
        return self
    
    def add_examples(
        self,
        examples: Dict[str, str],
        show_output: bool = True,
        code_block_lang: str = "python"
    ) -> 'ReadmeBuilder':
        """
        Add detailed examples section.
        
        Parameters
        ----------
        examples : dict
            Examples with code and optional output.
        show_output : bool, default=True
            Whether to show expected output.
        code_block_lang : str, default="python"
            Language for code blocks.
        """
        self._toc_entries.append("Examples")
        lines = ["## 📚 Examples", ""]
        
        for title, code in examples.items():
            lines.append(f"### {title}")
            lines.append(f"```{code_block_lang}")
            lines.append(code.strip())
            lines.append("```")
            if show_output:
                lines.append("")
                lines.append("**Output:**")
                lines.append("```")
                lines.append("Example output will appear here")
                lines.append("```")
            lines.append("")
        
        self.sections.append("\n".join(lines))
        return self
    
    def add_tests(self, test_command: str = "pytest") -> 'ReadmeBuilder':
        """Add testing section."""
        self._toc_entries.append("Testing")
        lines = [
            "## 🧪 Running Tests",
            "",
            "To run the test suite:",
            "",
            "```bash",
            test_command,
            "```",
            "",
            "For test coverage:",
            "",
            "```bash",
            f"{test_command} --cov=src --cov-report=html",
            "```"
        ]
        self.sections.append("\n".join(lines))
        return self
    
    def add_api_reference(self, modules: Optional[List[str]] = None) -> 'ReadmeBuilder':
        """Add API reference section."""
        self._toc_entries.append("API Reference")
        lines = ["## 📖 API Reference", ""]
        
        if modules:
            lines.append("### Modules")
            for module in modules:
                lines.append(f"- `{module}`")
            lines.append("")
        
        lines.append("For detailed API documentation, see the [full documentation](docs/).")
        
        self.sections.append("\n".join(lines))
        return self
    
    def add_contributing(self, guidelines: Optional[str] = None) -> 'ReadmeBuilder':
        """Add contributing section."""
        self._toc_entries.append("Contributing")
        lines = ["## 🤝 Contributing", ""]
        
        if guidelines:
            lines.append(guidelines)
        else:
            lines.append("Contributions are welcome! Please follow these steps:")
            lines.append("")
            lines.append("1. Fork the repository")
            lines.append("2. Create a feature branch (`git checkout -b feature/amazing-feature`)")
            lines.append("3. Commit your changes (`git commit -m 'Add amazing feature'`)")
            lines.append("4. Push to the branch (`git push origin feature/amazing-feature`)")
            lines.append("5. Open a Pull Request")
        
        self.sections.append("\n".join(lines))
        return self
    
    def add_license(self, license_name: str, holder: str, year: Optional[int] = None) -> 'ReadmeBuilder':
        """Add license section."""
        self._toc_entries.append("License")
        year = year or datetime.now().year
        lines = [
            "## 📄 License",
            "",
            f"This project is licensed under the {license_name} License.",
            f"Copyright (c) {year} {holder}",
            "",
            f"See the [LICENSE](LICENSE) file for details."
        ]
        self.sections.append("\n".join(lines))
        return self
    
    def add_author(self, author: str, email: Optional[str] = None, github: Optional[str] = None) -> 'ReadmeBuilder':
        """Add author section."""
        lines = ["## 👤 Author", ""]
        
        author_line = f"**{author}**"
        if email:
            author_line += f" - {email}"
        if github:
            author_line += f" - [GitHub]({github})"
        
        lines.append(author_line)
        self.sections.append("\n".join(lines))
        return self
    
    def add_acknowledgments(self, acknowledgments: List[str]) -> 'ReadmeBuilder':
        """Add acknowledgments section."""
        self._toc_entries.append("Acknowledgments")
        lines = ["## 🙏 Acknowledgments", ""]
        for ack in acknowledgments:
            lines.append(f"- {ack}")
        self.sections.append("\n".join(lines))
        return self
    
    def add_custom_section(
        self,
        title: str,
        content: str,
        add_to_toc: bool = True
    ) -> 'ReadmeBuilder':
        """Add a custom section."""
        if add_to_toc:
            self._toc_entries.append(title)
        self.sections.append(f"## {title}\n\n{content}")
        return self
    
    def build(self, clean: bool = True) -> str:
        """
        Build the final README content.
        
        Parameters
        ----------
        clean : bool, default=True
            Remove empty sections and normalize whitespace.
        
        Returns
        -------
        str
            Complete README markdown content.
        """
        # Join all sections with double newlines
        content = "\n\n".join(filter(None, self.sections))
        
        if clean:
            # Remove multiple consecutive newlines
            content = re.sub(r'\n{3,}', '\n\n', content)
            # Strip leading/trailing whitespace
            content = content.strip()
        
        return content
    
    def _get_badge_color(self, name: str, value: str) -> str:
        """Get appropriate color for badge based on name and value."""
        color_map = {
            "python": "blue",
            "version": "blue",
            "license": "green",
            "coverage": "green" if ">" in str(value) else "yellow",
            "tests": "green" if "passing" in str(value).lower() else "red",
            "docs": "blue",
            "pypi": "blue",
        }
        
        for key, color in color_map.items():
            if key in name.lower():
                return color
        
        return "blue"


def readme_template(
    name: str = "My Project",
    description: str = "A short description of the project.",
    version: Optional[str] = None,
    badges: Optional[Dict[str, Union[str, Dict[str, str]]]] = None,
    installation_methods: Optional[Dict[str, str]] = None,
    requirements: Optional[List[str]] = None,
    python_version: Optional[str] = None,
    usage_examples: Optional[Dict[str, str]] = None,
    features: Optional[Union[List[str], Dict[str, str]]] = None,
    features_style: FeatureStyle = FeatureStyle.LIST,
    examples: Optional[Dict[str, str]] = None,
    test_command: str = "pytest",
    license_name: str = "MIT",
    author: str = "Your Name",
    author_email: Optional[str] = None,
    author_github: Optional[str] = None,
    acknowledgments: Optional[List[str]] = None,
    add_toc: bool = True,
    min_toc_sections: int = 4,
    add_timestamp_comment: bool = True,
    from_pyproject: Optional[Union[str, Path]] = None,
    extra_sections: Optional[Dict[str, str]] = None,
    images: Optional[List[str]] = None,
) -> str:
    """
    Generate a professional README.md template with comprehensive features.
    
    This function creates a well-structured README file with automatic table
    of contents, badge generation, multiple installation methods, code examples,
    and much more.
    
    Parameters
    ----------
    name : str, default="My Project"
        Project name. Will be normalized for badges and installation.
        
    description : str, default="A short description..."
        Project description. Appears in the description section.
        
    version : str, optional
        Project version. Added to title if provided.
        
    badges : dict, optional
        Badge configurations. Supports simple and advanced formats.
        Simple: {"python": "3.10", "license": "MIT"}
        Advanced: {"coverage": {"label": "coverage", "value": "95%", "color": "green"}}
        
    installation_methods : dict, optional
        Installation methods. Example:
        {
            "pip": "pip install mypackage",
            "poetry": "poetry add mypackage",
            "from source": "git clone https://github.com/..."
        }
        
    requirements : list, optional
        System requirements. Example: ["Python 3.8+", "Git"]
        
    python_version : str, optional
        Required Python version. Example: "3.8"
        
    usage_examples : dict, optional
        Usage examples with titles. Example:
        {
            "Basic": "import mypackage\nmypackage.hello()",
            "Advanced": "from mypackage import Client\nclient = Client()"
        }
        
    features : list or dict, optional
        Project features. List: ["Fast", "Lightweight"]
        Dict: {"Fast": "Processes 1M rows/sec", "Lightweight": "No dependencies"}
        
    features_style : FeatureStyle, default="list"
        Display style for features: "list", "table", or "grid"
        
    examples : dict, optional
        Detailed examples with expected output.
        
    test_command : str, default="pytest"
        Command to run tests.
        
    license_name : str, default="MIT"
        License name for the license section.
        
    author : str, default="Your Name"
        Author name.
        
    author_email : str, optional
        Author email address.
        
    author_github : str, optional
        Author GitHub profile URL.
        
    acknowledgments : list, optional
        List of acknowledgments or credits.
        
    add_toc : bool, default=True
        Whether to add table of contents automatically.
        
    min_toc_sections : int, default=4
        Minimum sections required to show TOC.
        
    add_timestamp_comment : bool, default=True
        Add generation timestamp comment at the top.
        
    from_pyproject : str or Path, optional
        Path to pyproject.toml to auto-populate fields.
        
    extra_sections : dict, optional
        Additional custom sections. Key is section title, value is content.
        
    images : list, optional
        List of image URLs to include in the README.
        
    Returns
    -------
    str
        Complete README markdown content.
        
    Examples
    --------
    Basic usage:
    >>> readme = readme_template(
    ...     name="My Awesome Package",
    ...     description="A package that does amazing things",
    ...     version="1.0.0",
    ...     features=["Fast", "Easy to use", "Well documented"]
    ... )
    
    Advanced usage with all features:
    >>> readme = readme_template(
    ...     name="Advanced Package",
    ...     description="Enterprise-grade solution",
    ...     badges={
    ...         "python": "3.10",
    ...         "license": "MIT",
    ...         "coverage": {"label": "coverage", "value": "95%", "color": "green"}
    ...     },
    ...     installation_methods={
    ...         "pip": "pip install advanced-package",
    ...         "poetry": "poetry add advanced-package"
    ...     },
    ...     usage_examples={
    ...         "Basic": "from advanced import Client\nclient = Client()",
    ...         "Advanced": "client.process_large_data(file='data.csv')"
    ...     },
    ...     features={
    ...         "High Performance": "Processes 1M records/second",
    ...         "Type Hints": "Full type annotation support",
    ...         "Async Support": "Built with asyncio"
    ...     },
    ...     features_style="table",
    ...     examples={
    ...         "Quick Start": "client = Client()\nresult = client.run()"
    ...     },
    ...     author="Jane Doe",
    ...     author_github="https://github.com/janedoe"
    ... )
    
    Auto-detect from pyproject.toml:
    >>> readme = readme_template(from_pyproject="pyproject.toml")
    
    Notes
    -----
    - Badges use shields.io by default with color selection
    - Table of contents is automatically generated with proper anchors
    - Empty sections are omitted automatically
    - Supports both list and dictionary formats for features
    - Code blocks are properly formatted with language specifiers
    - Images can be added anywhere using the extra_sections parameter
    """
    
    # Auto-detect from pyproject.toml
    if from_pyproject:
        try:
            import tomllib
            pyproject_path = Path(from_pyproject)
            if pyproject_path.exists():
                with open(pyproject_path, "rb") as f:
                    data = tomllib.load(f)
                
                project = data.get("project", {})
                if project:
                    name = project.get("name", name)
                    description = project.get("description", description)
                    version = project.get("version", version)
                    
                    # Extract author from authors list
                    authors = project.get("authors", [])
                    if authors and isinstance(authors, list):
                        first_author = authors[0]
                        if isinstance(first_author, dict):
                            author = first_author.get("name", author)
                            author_email = first_author.get("email", author_email)
                    
                    # Get license
                    license_info = project.get("license", {})
                    if license_info:
                        license_name = license_info.get("text", license_name)
                    
                    # Get Python version requirement
                    python_requires = project.get("requires-python", "")
                    if python_requires:
                        python_version = python_requires.replace(">=", "").replace("<", "").strip()
        except (ImportError, tomllib.TOMLDecodeError, KeyError):
            pass  # Fall back to provided values
    
    # Normalize project name for badges
    normalized_name = name.lower().replace(" ", "-")
    
    # Builder instance
    builder = ReadmeBuilder()
    
    # Add timestamp comment if requested
    if add_timestamp_comment:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        builder.add_custom_section(
            title="",
            content=f"<!-- Generated by readme_template on {timestamp} -->",
            add_to_toc=False
        )
    
    # Add title
    builder.add_title(name, version)
    
    # Add badges with defaults if not provided
    if badges is None:
        badges = {
            "python": python_version or "3.8",
            "license": license_name,
            "version": version or "latest"
        }
        # Add PyPI badge if name looks like a package
        if normalized_name:
            badges["pypi"] = normalized_name
    
    builder.add_badges(badges)
    
    # Add description
    builder.add_description(description)
    
    # Determine TOC sections
    toc_sections = ["Description"]
    if installation_methods or requirements or python_version:
        toc_sections.append("Installation")
    if usage_examples:
        toc_sections.append("Usage")
    if features:
        toc_sections.append("Features")
    if examples:
        toc_sections.append("Examples")
    if test_command:
        toc_sections.append("Testing")
    if extra_sections:
        toc_sections.extend(extra_sections.keys())
    toc_sections.extend(["License", "Author"])
    if acknowledgments:
        toc_sections.append("Acknowledgments")
    
    # Add TOC
    if add_toc and len(toc_sections) >= min_toc_sections:
        builder.add_toc(toc_sections, min_toc_sections)
    
    # Add sections
    builder.add_installation(
        methods=installation_methods,
        requirements=requirements,
        python_version=python_version
    )
    
    if usage_examples:
        builder.add_usage(usage_examples)
    
    if features:
        builder.add_features(features, style=features_style)
    
    if examples:
        builder.add_examples(examples)
    
    builder.add_tests(test_command)
    
    # Add extra sections
    if extra_sections:
        for title, content in extra_sections.items():
            builder.add_custom_section(title, content)
    
    # Add images if provided
    if images:
        image_section = "\n".join([f"![Image]({url})" for url in images])
        builder.add_custom_section("📸 Screenshots", image_section)
    
    # Add license and author
    builder.add_license(license_name, author)
    builder.add_author(author, author_email, author_github)
    
    if acknowledgments:
        builder.add_acknowledgments(acknowledgments)
    
    # Build and return
    return builder.build()


def write_readme(path: Union[str, Path] = "README.md", **kwargs) -> None:
    """
    Generate a README.md file and write it directly to disk.
    
    Parameters
    ----------
    path : str or Path, default="README.md"
        Path where to write the README file.
    **kwargs
        Additional arguments passed to readme_template().
        
    Examples
    --------
    >>> write_readme("README.md", name="My Package", description="Awesome package")
    """
    content = readme_template(**kwargs)
    path_obj = Path(path)
    path_obj.write_text(content, encoding="utf-8")
