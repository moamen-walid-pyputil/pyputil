#!/usr/bin/env python3

# -*- coding: utf-8 -*-

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
pyputil.tree.cli - Professional Command Line Interface for Dependency Analysis
================================================================================

A comprehensive, production-ready CLI tool for analyzing and visualizing Python 
package dependencies with enterprise-grade features, beautiful terminal output,
and extensive customization options.

This module provides the main command-line interface for the pyputil.tree
package, allowing users to analyze package dependencies, detect conflicts,
filter by various criteria, and export results in multiple formats.

Key Features:
-------------
- Recursive dependency tree generation with configurable depth
- Multiple output formats (text, JSON, YAML, HTML, DOT, Mermaid)
- Advanced filtering (platform, Python version, optional/dev deps, regex)
- **NEW** Shared dependency deduplication (merge, collapse, or mark)
- Cycle detection and conflict analysis
- Parallel processing for large trees
- Beautiful terminal output with colors
- Statistics and metrics collection
- Orphaned package detection

-------------------------------------------------------------------------------
TABLE OF CONTENTS
-------------------------------------------------------------------------------
1. OVERVIEW
2. QUICK START
3. COMMAND REFERENCE
4. OUTPUT FORMATS
5. FILTERING OPTIONS
6. EXPORT CAPABILITIES
7. DEDUPLICATION FEATURES
8. EXAMPLES
9. EXIT CODES
10. ENVIRONMENT VARIABLES
11. TROUBLESHOOTING
-------------------------------------------------------------------------------
"""

import argparse
import sys
import json
import re
import os
from typing import Optional, List, Dict, Any, Tuple, Union
from pathlib import Path
from datetime import datetime
import textwrap
import warnings

# Ignore any errors, warnings, issues for clean CLI screen
# This prevents warning messages from cluttering the terminal output,
# ensuring a clean professional appearance. Users can still see
# critical errors, but informational warnings are suppressed.
warnings.simplefilter("ignore")

# Add parent directory to path for standalone execution.
# When the script is run directly (not installed via pip), Python
# may not find the pyputil package because it's in a parent directory.
# Adding the grandparent directory to sys.path allows imports to work
# correctly in development environments.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# =============================================================================
# IMPORT LIBRARY COMPONENTS WITH FALLBACKS
# =============================================================================

# We attempt to import all necessary functions and classes from the
# pyputil.tree library. If the import fails (e.g., the library is not
# installed or there are missing dependencies), we set IMPORT_SUCCESS
# to False and capture the error message. This allows the CLI to
# gracefully handle missing dependencies and provide a clear error
# message to the user instead of a cryptic ImportError traceback.

try:
    # Import core tree functions
    from pyputil.tree import (
        print_tree,           # Legacy function for printing trees
        get_tree,             # Function to get tree as structured data
        find_conflicts,       # Detect version conflicts in tree
        calculate_tree_metrics, # Calculate statistics about tree
        find_orphaned_packages, # Find missing/not installed packages
        analyze_tree_comprehensive, # Complete analysis of tree
        tree_to_requirements, # Convert tree to requirements.txt format
        compare_trees,        # Compare two dependency trees
        get_package_info,     # Get detailed info about a package
        __version__     # Package version
    )
    
    # Import core models
    from pyputil.tree.core.models import OutputFormat, DependencyType
    
    # Import builder components for advanced configuration
    from pyputil.tree.tree.builder import DuplicateHandling, BuildStrategy, CacheStrategy
    
    # Import printer components for export functionality
    from pyputil.tree.tree.printer import DependencyTreePrinter, TreeOutputFormat, TreeStyle
    
    # Flag indicating successful import of all required components
    IMPORT_SUCCESS = True
    
except ImportError as e:
    # Capture the import error for later display to the user
    IMPORT_SUCCESS = False
    IMPORT_ERROR = str(e)


# =============================================================================
# TERMINAL OUTPUT FORMATTER
# =============================================================================

class TerminalFormatter:
    """
    Professional terminal output formatter with ANSI color support.
    
    This class provides comprehensive text formatting capabilities for
    terminal output, including colors, styles, tables, progress indicators,
    and structured data presentation. It automatically detects whether
    the terminal supports ANSI color codes and adjusts output accordingly.
    
    The formatter handles:
    - ANSI color code application with automatic detection
    - Terminal width detection for proper text wrapping
    - Styled messages for different severity levels (success, error, warning, info)
    - Section headers with three visual levels
    - Formatted ASCII tables with configurable column alignments
    - Progress bars with percentage and visual bar display
    - Tree structure printing with proper indentation
    - Summary boxes with aligned key-value pairs
    - Detailed error information with traceback display
    - Decorative application banner
    
    The class is designed to be the sole output manager for the CLI,
    ensuring consistent styling across all user-facing messages.
    
    Attributes
    ----------
    COLORS : Dict[str, str]
        Class-level dictionary mapping color names to ANSI escape sequences.
        Includes foreground colors, background colors, and text styles.
    
    use_colorize : bool
        Instance-level flag indicating whether color output is enabled.
        This is True only when the user hasn't disabled colors AND the
        terminal actually supports ANSI escape sequences.
    
    width : int
        Current terminal width in characters. Used for creating full-width
        separators and centering text in headers and banners.
    
    Examples
    --------
    >>> # Create formatter with auto-detection
    >>> fmt = TerminalFormatter()
    >>> 
    >>> # Styled messages
    >>> print(fmt.success("Package installed"))
    ✓ Package installed (in green)
    >>> print(fmt.error("Failed to fetch"))
    ✗ Failed to fetch (in bold red)
    >>> print(fmt.warning("Deprecated package"))
    ⚠ Deprecated package (in yellow)
    >>> 
    >>> # Print a formatted table
    >>> fmt.print_table(
    ...     headers=["Package", "Version", "Status"],
    ...     rows=[["requests", "2.28.1", "installed"]]
    ... )
    Package     Version    Status
    ─────────────────────────────
    requests    2.28.1     installed
    """
    
    # ANSI color codes dictionary
    # This mapping provides human-readable names for ANSI escape sequences.
    # The 'reset' code clears all formatting, preventing color bleeding
    # to subsequent terminal output. Each color/style code begins an
    # ANSI escape sequence starting with '\\033[' (the escape character)
    # followed by a numeric code and ending with 'm'.
    COLORS = {
        # Text formatting styles
        'reset': '\033[0m',          # Reset all formatting to terminal default
        'bold': '\033[1m',           # Bold/bright text (increases intensity)
        'dim': '\033[2m',            # Dimmed/faint text (reduces intensity)
        'italic': '\033[3m',         # Italic text (not supported on all terminals)
        'underline': '\033[4m',      # Underlined text
        'blink': '\033[5m',          # Blinking text (often not supported)
        'reverse': '\033[7m',        # Reverse video (swap foreground/background)
        'hidden': '\033[8m',         # Hidden/invisible text (rarely used)
        
        # Foreground text colors
        'black': '\033[30m',         # Black text
        'red': '\033[31m',           # Red text (for errors and critical issues)
        'green': '\033[32m',         # Green text (for success messages)
        'yellow': '\033[33m',        # Yellow text (for warnings)
        'blue': '\033[34m',          # Blue text (for headers)
        'magenta': '\033[35m',       # Magenta text (for questions/prompts)
        'cyan': '\033[36m',          # Cyan text (for informational messages)
        'white': '\033[37m',         # White text (default)
        
        # Background colors
        'bg_black': '\033[40m',      # Black background
        'bg_red': '\033[41m',        # Red background
        'bg_green': '\033[42m',      # Green background
        'bg_yellow': '\033[43m',     # Yellow background
        'bg_blue': '\033[44m',       # Blue background
        'bg_magenta': '\033[45m',    # Magenta background
        'bg_cyan': '\033[46m',       # Cyan background
        'bg_white': '\033[47m',      # White background
    }
    
    def __init__(self, colorize: bool = True):
        """
        Initialize the terminal formatter with color support detection.
        
        This constructor sets up the formatter by:
        1. Detecting whether the terminal supports ANSI colors
        2. Determining the terminal width for formatting purposes
        3. Configuring the color output based on user preference and support
        
        The color detection works across multiple platforms:
        - Windows: Uses Windows API to check console mode
        - Unix/Linux/macOS: Assumes ANSI support if stdout is a TTY
        
        Parameters
        ----------
        colorize : bool, default=True
            Whether to attempt using ANSI colors. If True, colors will be
            used only if the terminal supports them. If False, all output
            will be plain text without any ANSI escape sequences.
        
        Notes
        -----
        - When stdout is redirected to a file or pipe, color is automatically
          disabled to prevent ANSI codes from appearing in the output.
        - On Windows, colors require Windows 10 or later with ANSI support
          enabled in the console.
        """
        # Enable colorization only if both:
        # 1. The user requested colors (colorize=True)
        # 2. The terminal actually supports ANSI escape sequences
        # This prevents garbage characters when piping output to files.
        self.use_colorize = colorize and self._supports_color()
        
        # Determine the terminal width for formatting purposes
        # Used by header(), print_banner(), and other methods that need
        # to create full-width separators and decorations.
        self.width = self._get_terminal_width()
    
    def _supports_color(self) -> bool:
        """
        Detect if the terminal supports ANSI colors.
        
        This method performs multi-platform terminal detection to determine
        if ANSI color escape sequences will be properly rendered.
        
        Detection logic:
        1. Check if stdout is connected to an interactive terminal (TTY)
           - If not (e.g., piped to a file or another program), return False
        2. On Windows, call GetConsoleMode API to check if the console
           supports ANSI escape sequences (enabled by default in Windows 10+)
        3. On Unix-like systems (Linux, macOS), assume ANSI support if stdout
           is a TTY (modern terminals universally support ANSI)
        
        Returns
        -------
        bool
            True if the terminal supports ANSI color output, False otherwise.
            Returns False when:
            - stdout is not connected to a terminal (piped/redirected output)
            - Running on Windows with a console that doesn't support ANSI
            - Any error occurs during detection (e.g., missing APIs)
        
        Examples
        --------
        >>> fmt = TerminalFormatter()
        >>> if fmt._supports_color():
        ...     print("ANSI colors available")
        ... else:
        ...     print("Plain text output only")
        """
        # Check if stdout is connected to an interactive terminal (TTY).
        # When output is redirected to a file with '>', isatty() returns False.
        # We disable colors in this case to prevent ANSI codes from appearing
        # in the file content.
        if not sys.stdout.isatty():
            return False
        
        # Windows-specific color support detection
        # Uses the Windows API to query console mode. On modern Windows
        # (Windows 10+ with ANSI support enabled), GetConsoleMode will
        # return a non-zero value indicating that the console supports
        # virtual terminal sequences (ANSI escape codes).
        if os.name == 'nt':
            try:
                import ctypes
                # GetConsoleMode: Windows API function to retrieve the
                # console mode for the standard output handle.
                # GetStdHandle(-11) returns the handle for standard output.
                # If the call succeeds (returns non-zero), ANSI is supported.
                return ctypes.windll.kernel32.GetConsoleMode(
                    ctypes.windll.kernel32.GetStdHandle(-11), 
                    ctypes.byref(ctypes.c_ulong())
                ) != 0
            except:
                # If any exception occurs (missing DLL, permission denied,
                # etc.), assume no color support for safety.
                return False
        
        # On Unix-like systems (Linux, macOS, BSD, etc.), ANSI colors are
        # universally supported in modern terminals. If stdout is a TTY,
        # we can safely enable color output.
        return True
    
    def _get_terminal_width(self) -> int:
        """
        Get the terminal width in character columns.
        
        Uses the shutil.get_terminal_size() function, which is the standard
        cross-platform way to determine terminal dimensions in Python.
        
        Returns
        -------
        int
            Terminal width in columns. Returns 80 (the traditional default
            terminal width) if the width cannot be determined (e.g., when
            running in a non-interactive environment or on a system without
            terminal size support).
        
        Examples
        --------
        >>> fmt = TerminalFormatter()
        >>> width = fmt._get_terminal_width()
        >>> print(f"Terminal is {width} columns wide")
        Terminal is 120 columns wide
        """
        try:
            import shutil
            # get_terminal_size() returns an os.terminal_size namedtuple
            # with two attributes: 'columns' (width) and 'lines' (height).
            return shutil.get_terminal_size().columns
        except:
            # Fallback to 80 columns, which is the traditional terminal width
            # and is safe for most environments. This ensures that full-width
            # separators don't exceed the terminal width.
            return 80
    
    def colorize(self, text: str, color: str, bold: bool = False,
                 italic: bool = False, underline: bool = False) -> str:
        """
        Apply ANSI styling to text.
        
        This is the core styling method that wraps text with ANSI escape
        sequences for colors and text styles. Multiple style attributes
        can be combined (e.g., bold red text). If color support is disabled
        (self.use_colorize is False), the text is returned unchanged.
        
        Parameters
        ----------
        text : str
            The text content to be styled. This can be any string that will
            be displayed in the terminal.
        
        color : str
            Color name to apply. Must be one of the keys in the COLORS
            dictionary. Common values include:
            - 'red': Red text (errors, critical issues)
            - 'green': Green text (success messages)
            - 'yellow': Yellow text (warnings)
            - 'blue': Blue text (headers)
            - 'cyan': Cyan text (informational)
            - 'magenta': Magenta text (questions/prompts)
            - 'white': White text (default)
            - 'dim': Dimmed text (debug messages)
        
        bold : bool, default=False
            Apply bold/bright text styling. When True, text appears with
            increased intensity. On some terminals, bold may also change
            the text color to a brighter shade.
        
        italic : bool, default=False
            Apply italic text styling. When True, text appears slanted.
            Note that italic support varies across terminals and may not
            be visible in all environments.
        
        underline : bool, default=False
            Apply underline text styling. When True, the text is displayed
            with a line underneath it.
        
        Returns
        -------
        str
            The styled text string with ANSI escape sequences applied.
            The string begins with the appropriate color/style codes and
            ends with the reset code ('\\033[0m') to prevent color bleeding.
            If self.use_colorize is False, returns the original text unchanged.
        
        Examples
        --------
        >>> fmt = TerminalFormatter()
        >>> fmt.colorize("Error", "red", bold=True)
        '\\033[1m\\033[31mError\\033[0m'
        
        >>> fmt.colorize("Debug info", "dim")
        '\\033[2mDebug info\\033[0m'
        
        >>> fmt.colorize("Note", "cyan", italic=True)
        '\\033[3m\\033[36mNote\\033[0m'
        """
        # If colorization is globally disabled (either user disabled it or
        # terminal doesn't support it), return plain text without ANSI codes.
        if not self.use_colorize:
            return text
        
        # Collect all ANSI codes to apply.
        # The order of codes matters: style codes (bold, italic, underline)
        # should come before color codes for consistent behavior across
        # different terminal emulators.
        codes = []
        
        # Add the foreground/text color code if specified
        if color in self.COLORS:
            codes.append(self.COLORS[color])
        
        # Add text style codes (applied after color for better rendering)
        if bold:
            codes.append(self.COLORS['bold'])
        if italic:
            codes.append(self.COLORS['italic'])
        if underline:
            codes.append(self.COLORS['underline'])
        
        # Return text wrapped with ANSI codes at the beginning and reset at the end
        # The reset code is essential to prevent style leakage to subsequent output.
        return f"{''.join(codes)}{text}{self.COLORS['reset']}"
    
    def success(self, text: str) -> str:
        """
        Format a success message with a checkmark and green color.
        
        Success messages indicate that an operation completed successfully
        (e.g., "Package installed", "Tree built successfully").
        
        Parameters
        ----------
        text : str
            The success message text to display.
        
        Returns
        -------
        str
            Formatted success message: "✓ {text}" in green.
        
        Examples
        --------
        >>> fmt = TerminalFormatter()
        >>> print(fmt.success("Dependency tree generated"))
        ✓ Dependency tree generated (in green)
        """
        return self.colorize(f"✓ {text}", 'green')
    
    def error(self, text: str) -> str:
        """
        Format an error message with a cross mark and bold red color.
        
        Error messages indicate that an operation failed (e.g., "Package not
        found", "Failed to fetch metadata"). They are displayed prominently
        to catch the user's attention.
        
        Parameters
        ----------
        text : str
            The error message text to display.
        
        Returns
        -------
        str
            Formatted error message: "✗ {text}" in bold red.
        
        Examples
        --------
        >>> fmt = TerminalFormatter()
        >>> print(fmt.error("Package not installed"))
        ✗ Package not installed (in bold red)
        """
        return self.colorize(f"✗ {text}", 'red', bold=True)
    
    def warning(self, text: str) -> str:
        """
        Format a warning message with a warning sign and yellow color.
        
        Warning messages alert the user to potential issues that are not
        fatal but may require attention (e.g., "Deprecated package",
        "Circular dependency detected").
        
        Parameters
        ----------
        text : str
            The warning message text to display.
        
        Returns
        -------
        str
            Formatted warning message: "⚠ {text}" in yellow.
        
        Examples
        --------
        >>> fmt = TerminalFormatter()
        >>> print(fmt.warning("Package has optional dependencies missing"))
        ⚠ Package has optional dependencies missing (in yellow)
        """
        return self.colorize(f"⚠ {text}", 'yellow')
    
    def info(self, text: str) -> str:
        """
        Format an informational message with an info symbol and cyan color.
        
        Informational messages provide context, hints, or status updates
        without indicating success or failure (e.g., "Processing packages",
        "Loading metadata from cache").
        
        Parameters
        ----------
        text : str
            The informational message text to display.
        
        Returns
        -------
        str
            Formatted info message: "ℹ {text}" in cyan.
        
        Examples
        --------
        >>> fmt = TerminalFormatter()
        >>> print(fmt.info("Analyzing 42 packages"))
        ℹ Analyzing 42 packages (in cyan)
        """
        return self.colorize(f"ℹ {text}", 'cyan')
    
    def debug(self, text: str) -> str:
        """
        Format a debug message with a magnifying glass and dimmed text.
        
        Debug messages provide detailed technical information useful for
        troubleshooting. They are only shown when --debug or --verbose
        flags are used.
        
        Parameters
        ----------
        text : str
            The debug message text to display.
        
        Returns
        -------
        str
            Formatted debug message: "🔍 {text}" in dimmed style.
        
        Examples
        --------
        >>> fmt = TerminalFormatter()
        >>> print(fmt.debug("Cache hit for package requests"))
        🔍 Cache hit for package requests (dimmed)
        """
        return self.colorize(f"🔍 {text}", 'dim')
    
    def question(self, text: str) -> str:
        """
        Format a question prompt with a question mark and bold magenta color.
        
        Question prompts are used when user input is needed (interactive mode).
        They are displayed prominently to indicate that a response is expected.
        
        Parameters
        ----------
        text : str
            The question text to display, typically ending with a question
            about user input (e.g., "Proceed with analysis? [y/N]").
        
        Returns
        -------
        str
            Formatted question: "❓ {text}" in bold magenta.
        
        Examples
        --------
        >>> fmt = TerminalFormatter()
        >>> print(fmt.question("Continue?"))
        ❓ Continue? (in bold magenta)
        """
        return self.colorize(f"❓ {text}", 'magenta', bold=True)
    
    def header(self, text: str, level: int = 1) -> str:
        """
        Format a section header with decorative separators.
        
        Headers help organize output into logical sections. Three levels
        are supported, each with different visual prominence:
        
        Level 1: Major section - Full-width banner with double-line borders,
                 centered text, bold blue color. Used for main sections like
                 "ANALYSIS RESULTS" or "DEPENDENCY TREE".
        
        Level 2: Subsection - Single underline separator below header text,
                 bold cyan color. Used for subsections like "Statistics" or
                 "Conflicts Detected".
        
        Level 3: Minor section - Bullet-point prefix with bold white color.
                 Used for minor subsections within larger sections.
        
        Parameters
        ----------
        text : str
            The header text to display (e.g., "DEPENDENCY TREE").
        
        level : int, default=1
            Header level controlling visual prominence:
            - 1: Major section (banner style with equal signs)
            - 2: Subsection (underlined with dashes)
            - 3: Minor section (bullet point with bold text)
        
        Returns
        -------
        str
            Formatted header string with appropriate decorations.
            Includes leading newlines for visual separation from preceding
            content.
        
        Examples
        --------
        >>> fmt = TerminalFormatter(width=50)
        >>> print(fmt.header("ANALYSIS", level=1))
        \n==================================================\n                    ANALYSIS\n==================================================\n
        >>> print(fmt.header("Statistics", level=2))
        \nStatistics\n--------------------------------------------------\n
        >>> print(fmt.header("Details", level=3))
        \n• Details\n
        """
        if level == 1:
            # Level 1: Full-width header with equal sign borders
            # Creates a visually prominent banner spanning the entire width
            line = "=" * self.width
            return f"\n{self.colorize(line, 'blue', bold=True)}\n{self.colorize(f"  {text}  ".center(self.width), 'blue', bold=True)}\n{self.colorize(line, 'blue', bold=True)}\n"
        elif level == 2:
            # Level 2: Subsection with dashed underline
            # Creates a clear divider below the header text
            line = "-" * self.width
            return f"\n{self.colorize(text, 'cyan', bold=True)}\n{self.colorize(line, 'cyan')}\n"
        else:
            # Level 3: Minor header with bullet prefix
            # Compact header without separator lines
            return f"\n{self.colorize(f"• {text}", 'white', bold=True)}\n"
    
    def print_banner(self):
        """
        Print a decorative application banner to the terminal.
        
        This method prints a large, visually distinctive ASCII art banner
        showing the application name, version, and tagline. The banner is
        enclosed in a double-lined box made with Unicode box-drawing
        characters.
        
        The banner serves as a splash screen when the application starts
        in verbose mode, providing a professional appearance and clear
        application identification.
        
        The box uses cyan color for all elements. The title text uses
        bold cyan, and the tagline uses italic cyan for visual distinction.
        
        The banner includes:
        - ASCII art letters spelling "PYPUTIL"
        - Application version number
        - Tagline "Analyze • Visualize • Optimize"
        
        Examples
        --------
        >>> fmt = TerminalFormatter()
        >>> fmt.print_banner()
        ╔══════════════════════════════════════════════════════════════╗
        ║                                                              ║
        ║               Python Package Dependency Tree Analyzer        ║
        ║                           v3.1.0                             ║
        ║                  Analyze • Visualize • Optimize              ║
        ║                                                              ║
        ╚══════════════════════════════════════════════════════════════╝
        """
        banner = f"""
{self.colorize('╔' + '═' * 78 + '╗', 'cyan', bold=True)}
{self.colorize('║' + ' ' * 78 + '║', 'cyan')}
{self.colorize('║' + '   ██▓███   ██▓▒███████▒▓█████  ██▓▄▄▄█████▓ ██▀███  ▓█████   '.center(78) + '║', 'cyan', bold=True)}
{self.colorize('║' + '  ▓██░  ██▒▓██▒▒ ▒ ▒ ▄▀░▓█   ▀ ▓██▒▓  ██▒ ▓▒▓██ ▒ ██▒▓█   ▀   '.center(78) + '║', 'cyan', bold=True)}
{self.colorize('║' + '  ▓██░ ██▓▒▒██▒░ ▒ ▄▀▒░ ▒███   ▒██▒▒ ▓██░ ▒░▓██ ░▄█ ▒▒███     '.center(78) + '║', 'cyan', bold=True)}
{self.colorize('║' + '  ▒██▄█▓▒ ▒░██░  ▄▀▒   ░▒▓█  ▄ ░██░░ ▓██▓ ░ ▒██▀▀█▄  ▒▓█  ▄   '.center(78) + '║', 'cyan', bold=True)}
{self.colorize('║' + '  ▒██▒ ░  ░░██░▒███████▒░▒████▒░██░  ▒██▒ ░ ░██▓ ▒██▒░▒████▒  '.center(78) + '║', 'cyan', bold=True)}
{self.colorize('║' + '  ▒▓▒░ ░  ░░▓  ░▒▒ ▓░▒░▒░░ ▒░ ░░▓    ▒ ░░   ░ ▒▓ ░▒▓░░░ ▒░ ░  '.center(78) + '║', 'cyan', bold=True)}
{self.colorize('║' + '  ░▒ ░      ▒ ░░░▒ ▒ ░ ▒ ░ ░  ░ ▒ ░    ░      ░▒ ░ ▒░ ░ ░  ░  '.center(78) + '║', 'cyan', bold=True)}
{self.colorize('║' + '  ░░        ▒ ░░ ░ ░ ░ ░   ░    ▒ ░  ░        ░░   ░    ░     '.center(78) + '║', 'cyan', bold=True)}
{self.colorize('║' + '            ░    ░ ░       ░  ░ ░           ░        ░  ░  '.center(78) + '║', 'cyan', bold=True)}
{self.colorize('║' + ' ' * 78 + '║', 'cyan')}
{self.colorize('║' + f'  Python Package Dependency Tree Analyzer v{__version__}'.center(78) + '║', 'cyan')}
{self.colorize('║' + '  Analyze • Visualize • Optimize'.center(78) + '║', 'cyan', italic=True)}
{self.colorize('║' + ' ' * 78 + '║', 'cyan')}
{self.colorize('╚' + '═' * 78 + '╝', 'cyan', bold=True)}
"""
        print(banner)
    
    def print_table(self, headers: List[str], rows: List[List[Any]],
                   alignments: Optional[List[str]] = None) -> None:
        """
        Print a formatted table to terminal with proper column alignment.
        
        This method creates a visually appealing ASCII table with colored
        headers, separator lines, and aligned data. The table automatically
        calculates column widths based on the content, ensuring all data
        fits without truncation.
        
        Features:
        - Automatic column width calculation based on content
        - Colorized headers in bold cyan
        - Separator line using Unicode box-drawing characters
        - Green highlighting for package names (first column)
        - Status-based coloring (installed in green, other statuses in yellow)
        - Configurable column alignment (left, center, right)
        
        Parameters
        ----------
        headers : List[str]
            Column header names. Each string becomes a column header
            displayed in bold cyan at the top of the table.
        
        rows : List[List[Any]]
            Table data rows. Each inner list represents one row of data,
            with elements corresponding to the columns defined in headers.
            Elements can be of any type; they will be converted to strings
            via str() for display.
        
        alignments : List[str], optional
            Column alignment specifications for each column. Each element can be:
            - 'left': Left-align column content (default for all columns)
            - 'center': Center-align column content within its width
            - 'right': Right-align column content (useful for numeric data)
            If not provided or if list is shorter than number of columns,
            missing entries default to 'left' alignment.
        
        Returns
        -------
        None
            This method prints directly to stdout and does not return a value.
        
        Examples
        --------
        >>> fmt = TerminalFormatter()
        >>> fmt.print_table(
        ...     headers=["Package", "Version", "Status"],
        ...     rows=[
        ...         ["requests", "2.28.1", "installed"],
        ...         ["numpy", "1.24.0", "installed"],
        ...         ["unknown", "", "not_installed"]
        ...     ]
        ... )
        Package     Version    Status
        ─────────────────────────────
        requests    2.28.1     installed
        numpy       1.24.0     installed
        unknown                not_installed
        
        >>> # Right-align the version column
        >>> fmt.print_table(
        ...     headers=["Package", "Version", "Status"],
        ...     rows=[["requests", "2.28.1", "installed"]],
        ...     alignments=["left", "right", "left"]
        ... )
        Package     Version    Status
        ─────────────────────────────
        requests      2.28.1   installed
        """
        # Return early if there are no rows to display.
        # This prevents printing an empty table with just headers.
        if not rows:
            return
        
        # Step 1: Calculate column widths based on content
        # Start with the header widths as the minimum width for each column
        col_widths = [len(str(h)) for h in headers]
        
        # Expand column widths to accommodate the widest cell in each column
        for row in rows:
            for i, cell in enumerate(row):
                if i < len(col_widths):
                    col_widths[i] = max(col_widths[i], len(str(cell)))
        
        # Step 2: Add padding to each column for better readability
        # Add 2 characters of padding (1 space on each side of content)
        col_widths = [w + 2 for w in col_widths]
        
        # Step 3: Set default alignments for all columns if not specified
        # Default alignment is 'left' (most natural for text data)
        if alignments is None:
            alignments = ['left'] * len(headers)
        elif len(alignments) < len(headers):
            # Extend alignments list with 'left' for missing columns
            alignments = alignments + ['left'] * (len(headers) - len(alignments))
        
        # Step 4: Create format strings for each column
        # Python's string formatting mini-language:
        # - '<' : Left-align within the field width
        # - '^' : Center-align within the field width
        # - '>' : Right-align within the field width
        formats = []
        for width, align in zip(col_widths, alignments):
            if align == 'left':
                formats.append(f"{{:<{width}}}")
            elif align == 'center':
                formats.append(f"{{:^{width}}}")
            else:  # 'right'
                formats.append(f"{{:>{width}}}")
        
        # Combine all column formats into a single format string
        # This allows formatting entire rows with a single .format() call
        format_str = "".join(formats)
        
        # Step 5: Print the header row in bold cyan
        header_row = format_str.format(*[self.colorize(str(h), 'cyan', bold=True) for h in headers])
        print(header_row)
        
        # Step 6: Print a separator line using Unicode box-drawing characters
        # The line uses the '─' (U+2500) character for the horizontal line
        # Length matches the total width of all columns combined
        print(self.colorize("─" * len(header_row), 'dim'))
        
        # Step 7: Print each data row with appropriate styling
        # - First column (index 0): Package names shown in green
        # - Third column (index 2) with 'installed': Status shown in green
        # - Third column with other values: Status shown in yellow
        for row in rows:
            formatted_cells = []
            for i, cell in enumerate(row):
                cell_str = str(cell)
                
                # Apply special styling based on column index and content
                if i == 0:  # First column - package name
                    cell_str = self.colorize(cell_str, 'green')
                elif i == 2 and cell_str == 'installed':  # Status column - installed
                    cell_str = self.colorize(cell_str, 'green')
                elif i == 2 and cell_str != 'installed':  # Status column - not installed
                    cell_str = self.colorize(cell_str, 'yellow')
                
                formatted_cells.append(cell_str)
            
            # Print the formatted row using the combined format string
            print(format_str.format(*formatted_cells))
    
    def print_progress(self, current: int, total: int, prefix: str = "",
                       suffix: str = "", length: int = 50) -> None:
        """
        Print an animated progress bar to the terminal.
        
        This method creates an interactive progress bar that updates in
        place using carriage return (\\r). The bar shows:
        - Text prefix to indicate what operation is in progress
        - Visual bar with filled block characters (█) for completed portion
        - Light shade characters (░) for remaining portion
        - Percentage completion value
        - Custom suffix text
        
        The progress bar overwrites itself in place, creating a smooth
        animation effect. When current equals total (100% complete),
        a newline is printed to move to the next line, preventing the
        bar from being overwritten by subsequent output.
        
        Parameters
        ----------
        current : int
            Current progress value, should be between 0 and total.
            The percentage is calculated as (current / total) * 100.
        total : int
            Total value representing 100% completion. Must be greater
            than 0 to avoid division by zero errors.
        prefix : str, default=""
            Text to display before the progress bar. Can be used to
            indicate what operation is in progress.
            Example: "Processing packages"
        suffix : str, default=""
            Text to display after the progress bar. Can be used to
            show additional information like "3/10 packages processed".
        length : int, default=50
            The visual length of the progress bar in characters.
            The bar occupies exactly this many characters between the
            prefix and suffix text. Larger values create a longer bar.
        
        Returns
        -------
        None
            This method prints directly to stdout and does not return a value.
        
        Notes
        -----
        The progress bar uses special Unicode box-drawing characters:
        - '█' (U+2588, Full Block): Fills the completed portion
        - '░' (U+2591, Light Shade): Shows the remaining portion
        
        The \\r (carriage return) character moves the cursor to the beginning
        of the line, allowing subsequent print statements to overwrite the
        current line. This creates the animation effect.
        
        Examples
        --------
        >>> import time
        >>> fmt = TerminalFormatter()
        >>> for i in range(101):
        ...     fmt.print_progress(i, 100, "Processing:", f"{i}%")
        ...     time.sleep(0.01)
        Processing: |██████████████████████████████████████████████████| 100.0% 100%
        """
        # Calculate the completion percentage
        # Multiply by 100 to get a percentage value between 0 and 100
        percent = 100 * (current / float(total))
        
        # Calculate how many characters should be filled in the bar
        # Integer division (//) ensures whole character positions
        # Example: length=50, current=25, total=100 -> filled_length=12
        filled_length = int(length * current // total)
        
        # Create the visual bar:
        # - Filled portion uses '█' (U+2588 Full Block) for completed
        # - Remaining portion uses '░' (U+2591 Light Shade) for incomplete
        bar = '█' * filled_length + '░' * (length - filled_length)
        
        # Construct the complete progress line with carriage return
        # The \\r at the start moves the cursor back to the beginning
        # of the line, allowing the bar to be updated in place
        progress_text = f"\r{prefix} |{bar}| {percent:.1f}% {suffix}"
        
        # Apply cyan color to the progress text for visual appeal
        if self.use_colorize:
            progress_text = self.colorize(progress_text, 'cyan')
        
        # Print the progress bar without a newline (end='')
        # The \\r at the beginning of the next update will position the
        # cursor correctly for overwriting
        print(progress_text, end='')
        
        # When the operation is complete (current == total), print a newline
        # to move the cursor to the next line and prevent the progress bar
        # from being overwritten by subsequent output
        if current == total:
            print()
    
    def print_tree_structure(self, lines: List[str], indent: int = 0) -> None:
        """
        Print a pre-formatted tree structure with proper base indentation.
        
        This method prints a list of lines representing a tree structure,
        applying a base indentation level to each line. Empty lines are
        skipped to maintain clean output. This is useful for displaying
        nested data structures (like directory trees or dependency trees)
        where indentation represents hierarchy levels.
        
        The method assumes that the input lines already contain their own
        internal indentation for the tree structure. The `indent` parameter
        adds additional indentation to shift the entire tree to the right.
        
        Parameters
        ----------
        lines : List[str]
            List of formatted tree lines to print. Each line should already
            include its own internal indentation for the tree structure.
            Empty strings in the list are ignored and not printed.
        indent : int, default=0
            Base indentation level in spaces. This number of spaces is
            prepended to every non-empty line before printing. Can be used
            to offset the entire tree from the left margin or to nest it
            within other output.
        
        Returns
        -------
        None
            This method prints directly to stdout and does not return a value.
        
        Examples
        --------
        >>> fmt = TerminalFormatter()
        >>> tree_lines = [
        ...     "requests",
        ...     "  ├── certifi",
        ...     "  └── urllib3"
        ... ]
        >>> fmt.print_tree_structure(tree_lines, indent=2)
          requests
            ├── certifi
            └── urllib3
        """
        for line in lines:
            # Skip empty lines to maintain visual cleanliness
            # This also allows callers to include empty lines for spacing
            if line:
                # Print the line with the specified base indentation
                # The indentation is prepended as spaces before the line's
                # own content which already includes its internal indentation
                print(" " * indent + line)
    
    def print_summary(self, title: str, items: Dict[str, Any]) -> None:
        """
        Print a formatted summary box with aligned key-value pairs.
        
        This method creates a summary section with a level-2 header and
        aligned key-value pairs. Keys are displayed in bold yellow followed
        by a colon. The values are aligned after the longest key for clean
        visual presentation.
        
        This is ideal for displaying:
        - Statistics (total packages, max depth, etc.)
        - Configuration summaries
        - Analysis results
        - Performance metrics
        
        Parameters
        ----------
        title : str
            Summary section title. Displayed as a level-2 header
            (bold cyan with dashed underline) via the header() method.
        items : Dict[str, Any]
            Key-value pairs to display. Keys are converted to strings
            and displayed in title case with bold yellow coloring followed
            by a colon. Values are converted to strings via str().
            The display is aligned so all values start at the same column
            position (determined by the longest key length).
        
        Returns
        -------
        None
            This method prints directly to stdout via the header() method
            and print statements.
        
        Examples
        --------
        >>> fmt = TerminalFormatter()
        >>> stats = {
        ...     "total packages": 42,
        ...     "max depth": 5,
        ...     "average depth": 2.4,
        ...     "circular dependencies": 0
        ... }
        >>> fmt.print_summary("Tree Statistics", stats)
        
        Tree Statistics
        ────────────────────────────────────────────────
          Total Packages: 42
          Max Depth: 5
          Average Depth: 2.4
          Circular Dependencies: 0
        """
        # Display the section title as a level-2 header
        # This creates bold cyan text with a dashed underline separator
        self.header(title, level=2)
        
        # Calculate the maximum key length to determine the alignment column
        # This ensures all values start at the same horizontal position
        # Convert keys to strings and take the maximum length
        max_key_len = max(len(str(k)) for k in items.keys())
        
        # Print each key-value pair with proper alignment
        for key, value in items.items():
            # Format the key: convert to title case, add colon, apply styling
            # Example: "total packages" -> "Total Packages:"
            key_str = self.colorize(f"{str(key).title()}:", 'yellow', bold=True)
            
            # Print with alignment using Python's string formatting
            # The key is left-aligned within a field of width max_key_len + 2
            # The +2 accounts for the colon and the following space
            print(f"  {key_str:<{max_key_len + 2}} {value}")
    
    def print_error_detail(self, error: Exception, context: str = "") -> None:
        """
        Print comprehensive error details with traceback for debugging.
        
        This method provides a user-friendly error display that includes:
        - A prominent "ERROR OCCURRED" header (bold red)
        - Context about what operation was being performed (cyan)
        - The exception type name (cyan)
        - The exception message text (cyan)
        - A limited traceback (dimmed, 2 levels deep) for debugging
        
        The traceback display is limited to 2 levels to provide useful
        debugging information without overwhelming users with Python's
        full stack trace. This strikes a balance between usability and
        technical detail.
        
        Parameters
        ----------
        error : Exception
            The exception object to display. Its type, message, and
            optional traceback are extracted for display. If it has a
            __traceback__ attribute, it will be used for traceback display.
        context : str, default=""
            Additional context describing what operation was in progress
            when the error occurred. This helps users understand the
            error's origin even if the exception message is unclear.
            Example: "Analyzing package requests"
        
        Returns
        -------
        None
            This method prints directly to stdout and does not return a value.
        
        Examples
        --------
        >>> fmt = TerminalFormatter()
        >>> try:
        ...     raise ValueError("Invalid package name")
        ... except ValueError as e:
        ...     fmt.print_error_detail(e, "Analyzing package @invalid")
        
        ✗ ERROR OCCURRED
        ℹ Context: Analyzing package @invalid
        ℹ Type: ValueError
        ℹ Message: Invalid package name
        🔍
        Traceback:
          (most recent call last)
          ...
        """
        # Print a blank line for visual separation from preceding content
        print()
        
        # Display a prominent error heading in bold red
        # This immediately alerts the user to the error condition
        print(self.error("ERROR OCCURRED"))
        
        # Show the context if provided - helps identify where the error occurred
        if context:
            print(self.info(f"Context: {context}"))
        
        # Display the exception type name for classification (e.g., ValueError, TypeError)
        print(self.info(f"Type: {type(error).__name__}"))
        
        # Display the exception message for detailed information
        print(self.info(f"Message: {str(error)}"))
        
        # Show a partial traceback for debugging (if available)
        # Limit to 2 levels deep to provide useful context without excessive output
        if hasattr(error, '__traceback__'):
            import traceback
            print(self.debug("\nTraceback:"))
            # print_tb with limit=2 shows only the most recent 2 levels
            # of the stack trace, which is usually sufficient to identify
            # the error location without overwhelming the user
            traceback.print_tb(error.__traceback__, limit=2)
        
        # Add a final blank line for separation
        print()


# =============================================================================
# ARGUMENT PARSER AND HELP GENERATOR
# =============================================================================

class CLIArgumentParser(argparse.ArgumentParser):
    """
    Enhanced argument parser with professional help formatting.
    
    This class extends the standard argparse.ArgumentParser to provide
    beautifully formatted help output with categorized sections, colored
    examples, and detailed documentation.
    
    Features:
    - Branded header with application name and version
    - Colorized output in help text (uses TerminalFormatter)
    - Organized sections (Positional, Optional, Filter, Output, Deduplication)
    - Comprehensive examples with explanations
    - Exit code documentation
    - Environment variable documentation
    - Footer with links to documentation
    
    The parser disables the default -h/--help handling (via add_help=False
    in the parent) to allow complete control over help text formatting.
    This enables the professional, branded appearance of the help output.
    
    Parameters
    ----------
    *args : tuple
        Positional arguments passed to the parent ArgumentParser constructor.
        Typically includes the program name ('prog').
    **kwargs : dict
        Keyword arguments passed to the parent ArgumentParser constructor.
        Common arguments include:
        - description: Program description text displayed in help
        - epilog: Text displayed after the argument help
        - formatter_class: Class for formatting help text
          (typically RawDescriptionHelpFormatter to preserve formatting
          in description and epilog text)
    
    Attributes
    ----------
    formatter : TerminalFormatter
        Instance of TerminalFormatter used for applying colors and styles
        to the help output text.
    prog : str
        Program name (e.g., 'pyputil-tree') inherited from parent.
    description : str
        Program description text.
    
    Examples
    --------
    >>> parser = CLIArgumentParser(
    ...     description="Analyze Python package dependencies",
    ...     epilog="For more information, visit https://github.com/...",
    ...     formatter_class=argparse.RawDescriptionHelpFormatter
    ... )
    >>> parser.print_help()
    """
    
    def __init__(self, *args, **kwargs):
        """
        Initialize the enhanced argument parser.
        
        This constructor initializes the parent ArgumentParser with
        add_help=False to prevent the default argparse help handler
        from interfering with our custom formatted help display.
        It also creates a TerminalFormatter instance for formatting
        help output with colors and styles.
        
        Parameters
        ----------
        *args : tuple
            Positional arguments passed to the parent ArgumentParser
            constructor. These include:
            - prog: The program name (e.g., 'pyputil-tree')
            - usage: Custom usage string (optional)
            - description: Program description
            - epilog: Text after arguments
            - formatter_class: Help formatter class
        **kwargs : dict
            Keyword arguments passed to the parent ArgumentParser
            constructor.
        """
        # Initialize parent with add_help=False to disable the default
        # -h/--help flag handling. This allows us to provide our own
        # custom help formatting via the print_help() method.
        super().__init__(*args, **kwargs, add_help=False)
        
        # Create a TerminalFormatter for applying colors and styles
        # to the help output text. Colorize is set to True to enable
        # colored help output when the terminal supports it.
        self.formatter = TerminalFormatter(colorize=True)
    
    def print_help(self, file=None):
        """
        Print formatted help text with sections and examples.
        
        This method overrides the default argparse help printing to
        use our custom format_help() method, which generates a
        professionally formatted help text with sections, colors,
        and comprehensive documentation.
        
        Parameters
        ----------
        file : file object, optional
            Output file object to write help text to. If not specified,
            defaults to sys.stdout (standard output). Can be set to
            sys.stderr or any file-like object with a write() method.
        
        Returns
        -------
        None
            The help text is written to the specified file.
        """
        # Generate the formatted help text using the custom formatter
        help_text = self.format_help()
        
        # Write to the specified file, defaulting to stdout if none provided
        if file is None:
            file = sys.stdout
        file.write(help_text)
    
    def format_help(self) -> str:
        """
        Generate professionally formatted help text with enhanced presentation.
        
        This method builds the complete help text by assembling multiple
        sections in the following order:
        1. Header (branding with application name and version)
        2. Usage (syntax and quick start examples)
        3. Description (what the tool does and its features)
        4. Positional Arguments (required arguments)
        5. Optional Arguments (general options)
        6. Filter Options (filtering dependencies)
        7. Output Options (format and display options)
        8. Deduplication Options (shared dependency handling) - NEW!
        9. Comprehensive Examples (usage scenarios)
        10. Exit Codes (error code meanings)
        11. Environment Variables (configuration via environment)
        12. Footer (links to documentation)
        
        Each section is formatted separately with appropriate headers,
        separators, and colors. Sections are joined with double newlines
        for clear visual separation.
        
        Returns
        -------
        str
            Complete formatted help text ready for display in the terminal.
        """
        # Build help sections list in order
        sections = []
        
        # 1. Add the branded header at the top
        sections.append(self._format_header())
        
        # 2. Add usage information with quick examples
        sections.append(self._format_usage())
        
        # 3. Add description if provided by the caller
        if self.description:
            sections.append(self._format_section("DESCRIPTION", self.description))
        
        # 4. Get and add positional arguments section
        # These are required arguments like PACKAGE_NAME
        pos_args = self._get_positional_arguments()
        if pos_args:
            sections.append(self._format_arguments_section("POSITIONAL ARGUMENTS", pos_args))
        
        # 5. Get and add optional/general arguments section
        # These include --help, --version, --depth, --verbose, etc.
        opt_args = self._get_optional_arguments()
        if opt_args:
            sections.append(self._format_arguments_section("OPTIONAL ARGUMENTS", opt_args))
        
        # 6. Get and add filter-related arguments section
        # These include --pattern, --no-optional, --platform, etc.
        filter_args = self._get_filter_arguments()
        if filter_args:
            sections.append(self._format_arguments_section("FILTER OPTIONS", filter_args))
        
        # 7. Get and add output-related arguments section
        # These include --format, --output, --stats, --conflicts, etc.
        output_args = self._get_output_arguments()
        if output_args:
            sections.append(self._format_arguments_section("OUTPUT OPTIONS", output_args))
        
        # 8. Get and add deduplication-related arguments section (NEW!)
        # These include --deduplicate, --duplicate-handling
        dedup_args = self._get_deduplication_arguments()
        if dedup_args:
            sections.append(self._format_arguments_section("DEDUPLICATION OPTIONS", dedup_args))
        
        # 9. Add comprehensive examples section
        sections.append(self._format_examples())
        
        # 10. Add exit codes documentation
        sections.append(self._format_exit_codes())
        
        # 11. Add environment variables documentation
        sections.append(self._format_environment())
        
        # 12. Add footer with documentation links
        sections.append(self._format_footer())
        
        # Join all sections with double newlines for clear visual separation
        # This creates consistent spacing between logical sections
        return "\n\n".join(sections)
    
    def _format_header(self) -> str:
        """
        Format the help header with application branding.
        
        Creates a visually distinctive header box using Unicode
        box-drawing characters. The header box consists of:
        - Top border with double-line character (╔═╗)
        - Application name centered in bold cyan
        - Version number in cyan
        - Bottom border with double-line character (╚═╝)
        
        This professional header establishes the application's identity
        and brand immediately when help is requested.
        
        Returns
        -------
        str
            Formatted header string with box decorations and version information.
        """
        return f"""
{self.formatter.colorize('╔' + '═' * 78 + '╗', 'cyan', bold=True)}
{self.formatter.colorize('║' + ' PYTHON PACKAGE DEPENDENCY TREE ANALYZER '.center(78) + '║', 'cyan', bold=True)}
{self.formatter.colorize('║' + f' Version {__version__}'.center(78) + '║', 'cyan')}
{self.formatter.colorize('╚' + '═' * 78 + '╝', 'cyan', bold=True)}
"""
    
    def _format_section(self, title: str, content: str) -> str:
        """
        Format a help section with a title and content text.
        
        Creates a standard section format with:
        - Section title in bold yellow uppercase
        - Separator line of '─' characters matching title length in yellow
        - Content text displayed below the separator
        
        Parameters
        ----------
        title : str
            Section title (e.g., "DESCRIPTION", "USAGE"). Displayed in
            bold yellow uppercase with a separator line.
        content : str
            Section content text displayed below the separator. Can include
            line breaks and formatting; it will be used as-is.
        
        Returns
        -------
        str
            Formatted section string with title, separator, and content.
        """
        return f"""
{self.formatter.colorize(title, 'yellow', bold=True)}
{self.formatter.colorize('─' * len(title), 'yellow')}
{content}
"""
    
    def _format_arguments_section(self, title: str, arguments: List[tuple]) -> str:
        """
        Format an arguments section with a title and argument list.
        
        This method creates a section displaying a list of command-line
        arguments with their descriptions. Each argument is displayed with:
        - Argument name/flags in green for visibility
        - Description text wrapped to 70 columns
        - Initial indent of 2 spaces before each description
        - Subsequent lines indented 6 spaces (aligning with the description)
        
        The arguments are added in the order they appear in the list,
        maintaining their logical grouping (e.g., all filter options together).
        
        Parameters
        ----------
        title : str
            Section title (e.g., "POSITIONAL ARGUMENTS", "OPTIONAL ARGUMENTS").
            Displayed in bold yellow uppercase with a separator line.
        arguments : List[tuple]
            List of (argument_string, description_string) tuples.
            Each tuple contains:
            - argument_string: The argument name/flags as displayed to users
              (e.g., "-h, --help", "PACKAGE_NAME", "--pattern PATTERN")
            - description_string: Detailed description of what the argument
              does and how to use it. Can be multi-line; will be wrapped.
        
        Returns
        -------
        str
            Formatted arguments section with title and all argument entries
            properly formatted, indented, and colorized.
        """
        # Start with the section title and separator line
        lines = [
            self.formatter.colorize(title, 'yellow', bold=True),
            self.formatter.colorize('─' * len(title), 'yellow')
        ]
        
        # Add each argument with its description
        for arg_str, help_str in arguments:
            # Display the argument name/flags in green for visibility
            arg_display = self.formatter.colorize(arg_str, 'green')
            
            # Wrap the description text for readability:
            # - width=70: Maximum line width before wrapping (fits in 80-char terminals)
            # - initial_indent="  ": Two spaces before the first line of description
            # - subsequent_indent="      ": Six spaces before continuation lines
            #   This aligns continuation lines with the text of the first line,
            #   not with the argument name (which is left-aligned separately)
            help_display = textwrap.fill(help_str, width=70, initial_indent="  ", subsequent_indent="      ")
            
            # Add the argument line and its wrapped description
            # A blank line improves readability between arguments
            lines.append(f"\n  {arg_display}")
            lines.append(f"{help_display}")
        
        # Join all lines into a single string with newlines
        return "\n".join(lines)
    
    def _format_usage(self) -> str:
        """
        Format the usage section with command syntax and quick examples.
        
        This method creates a usage section showing:
        - The basic command syntax (usage: prog <package> [options])
        - Quick examples of common use cases
        - Examples colored with green '$' prompts to simulate a shell
        - Dimmed comments explaining each example
        
        The quick examples help new users understand how to use the tool
        without reading the entire documentation.
        
        Returns
        -------
        str
            Formatted usage section with syntax and quick-start examples.
        """
        usage = f"""usage: {self.prog} <package_name> [options]

{self.formatter.colorize('Quick Examples:', 'cyan', bold=True)}
  {self.formatter.colorize('$', 'green')} {self.prog} requests
  {self.formatter.colorize('$', 'green')} {self.prog} pandas --depth 3
  {self.formatter.colorize('$', 'green')} {self.prog} numpy --format json --output tree.json
  {self.formatter.colorize('$', 'green')} {self.prog} scikit-learn --pattern "^numpy|^scipy" --depth 2
  {self.formatter.colorize('$', 'green')} {self.prog} django --no-optional --no-dev

{self.formatter.colorize('With Deduplication (NEW!):', 'cyan', bold=True)}
  {self.formatter.colorize('$', 'green')} {self.prog} pyputil --deduplicate --duplicate-handling merge
  {self.formatter.colorize('$', 'green')} {self.prog} tensorflow --deduplicate --duplicate-handling collapse
  {self.formatter.colorize('$', 'green')} {self.prog} django --deduplicate --duplicate-handling mark-shared
"""
        return self._format_section("USAGE", usage)
    
    def _get_positional_arguments(self) -> List[tuple]:
        """
        Get the list of positional arguments with their descriptions.
        
        Positional arguments are required command-line arguments that must
        be provided in a specific order. For this tool, the main positional
        argument is PACKAGE_NAME, which specifies which Python package to
        analyze (e.g., 'requests', 'pandas', 'numpy').
        
        Returns
        -------
        List[tuple]
            List of (argument_name, description) tuples for positional
            arguments. Each tuple provides the argument name as it appears
            in help text and a detailed description with examples.
        """
        return [
            ("PACKAGE_NAME", "Name of the Python package to analyze (e.g., 'requests', 'pandas', 'numpy')")
        ]
    
    def _get_optional_arguments(self) -> List[tuple]:
        """
        Get the list of optional/general arguments with descriptions.
        
        Optional arguments are non-required flags and options that modify
        the tool's behavior. These include:
        - Help and version flags (-h, --help, -v, --version)
        - Depth control (-d, --depth)
        - Output formatting (--no-color, --verbose, --quiet, --debug)
        
        Returns
        -------
        List[tuple]
            List of (argument_flags, description) tuples for optional
            arguments. Each tuple provides the argument flags as they
            appear in help text and a detailed description of their effect.
        """
        return [
            ("-h, --help", "Show this help message and exit"),
            ("-v, --version", "Show program version and exit"),
            ("-d, --depth DEPTH", "Maximum recursion depth (default: 1, use -1 for unlimited)"),
            ("--no-color", "Disable colored terminal output"),
            ("--verbose, -V", "Enable verbose output with detailed information"),
            ("--quiet, -q", "Suppress all non-error output"),
            ("--debug", "Enable debug mode with traceback information"),
        ]
    
    def _get_filter_arguments(self) -> List[tuple]:
        """
        Get the list of filter-related arguments with descriptions.
        
        Filter arguments control which dependencies are displayed or
        processed. They allow users to narrow down the dependency tree
        based on:
        - Regex patterns (--pattern)
        - Dependency types (--no-optional, --no-dev)
        - Platform requirements (--platform)
        - Python version requirements (--python-version)
        - Extras groups (--include-extras)
        
        Returns
        -------
        List[tuple]
            List of (argument_flags, description) tuples for filter options.
            Each tuple provides the argument flags and a description of
            the filtering behavior with examples.
        """
        return [
            ("--pattern PATTERN", "Regex pattern to filter displayed packages (e.g., '^numpy|^scipy')"),
            ("--no-optional", "Exclude optional dependencies from the tree"),
            ("--no-dev, --no-development", "Exclude development dependencies (dev, test, docs)"),
            ("--platform PLATFORM", "Filter by platform: 'linux', 'windows', 'darwin', 'unix'"),
            ("--python-version VERSION", "Filter by Python version (e.g., '>=3.8', '==3.9')"),
            ("--include-extras EXTRAS", "Comma-separated list of extras to include (e.g., 'security,performance')"),
        ]
    
    def _get_output_arguments(self) -> List[tuple]:
        """
        Get the list of output-related arguments with descriptions.
        
        Output arguments control how the dependency tree results are
        presented. They include:
        - Output format selection (--format)
        - File output (--output)
        - Display toggles (--show-extras, --show-markers, --no-versions, --no-requirements)
        - Analysis options (--stats, --conflicts, --orphans)
        
        Returns
        -------
        List[tuple]
            List of (argument_flags, description) tuples for output options.
            Each tuple provides the argument flags and a description of
            the output behavior.
        """
        return [
            ("-f, --format FORMAT", "Output format: 'text' (default), 'json', 'yaml', 'html', 'dot', 'mermaid'"),
            ("-o, --output FILE", "Write output to file instead of stdout"),
            ("--show-extras", "Display package extras in requirement information"),
            ("--show-markers", "Display environment markers in requirement information"),
            ("--no-versions", "Hide package versions in output"),
            ("--no-requirements", "Hide version requirements from parent packages"),
            ("--stats", "Include tree statistics in output"),
            ("--conflicts", "Show conflict detection results"),
            ("--orphans", "Show orphaned (missing) packages"),
        ]
    
    def _get_deduplication_arguments(self) -> List[tuple]:
        """
        Get the list of deduplication-related arguments with descriptions (NEW!).
        
        Deduplication arguments control how shared dependencies (packages
        that appear multiple times in the tree) are handled. This feature
        dramatically reduces output clutter and makes large dependency
        trees more readable.
        
        The duplicate handling strategies:
        - show-all: Show all occurrences (no deduplication, complete accuracy)
        - deduplicate: Show each package once per depth level (balanced)
        - merge: Merge duplicate branches into single references (cleanest)
        - mark-shared: Show all occurrences but mark shared packages
        - collapse: Collapse duplicates with reference counts like "[x5]"
        
        Returns
        -------
        List[tuple]
            List of (argument_flags, description) tuples for deduplication
            options. Each tuple provides the argument flags and a detailed
            description of the deduplication behavior with strategy options.
        """
        return [
            ("--deduplicate", "Enable deduplication of shared dependencies (reduces output clutter)"),
            ("--duplicate-handling {show-all,deduplicate,merge,mark-shared,collapse}",
             "Strategy for handling duplicate dependencies:\n"
             "  show-all     - Show all occurrences (no deduplication)\n"
             "  deduplicate  - Show each package once per depth level\n"
             "  merge        - Merge duplicate branches into references\n"
             "  mark-shared  - Mark shared dependencies (adds [shared] tag)\n"
             "  collapse     - Collapse duplicates with reference counts (e.g., [x5])\n"
             "Default: deduplicate"),
        ]
    
    def _format_examples(self) -> str:
        """
        Format the comprehensive examples section with categorized usage.
        
        This method creates a detailed examples section showing various
        usage scenarios organized by category:
        - Basic Usage: Simple tree generation
        - Filtering: Using patterns, excluding dependency types
        - Deduplication: Handling shared dependencies (NEW!)
        - Export Formats: Different output formats
        - Analysis: Statistics, conflicts, orphans
        - Pipeline Examples: Shell scripting integration
        - Troubleshooting: Debug and verbose modes
        
        Each example shows the command with a dimmed comment explaining
        what it does, using colored '$' prompts to simulate a shell
        environment for visual appeal and clarity.
        
        Returns
        -------
        str
            Formatted examples section with categorized examples, each
            with a dimmed comment and colored prompt.
        """
        examples_text = f"""
{self.formatter.colorize('Basic Usage:', 'cyan', bold=True)}
  {self.formatter.colorize('# Show dependencies of requests', 'dim')}
  {self.formatter.colorize('$', 'green')} {self.prog} requests
  
  {self.formatter.colorize('# Show deeper tree', 'dim')}
  {self.formatter.colorize('$', 'green')} {self.prog} pandas --depth 3
  
  {self.formatter.colorize('# Show unlimited depth', 'dim')}
  {self.formatter.colorize('$', 'green')} {self.prog} tensorflow --depth -1

{self.formatter.colorize('Filtering:', 'cyan', bold=True)}
  {self.formatter.colorize('# Show only numpy and scipy dependencies', 'dim')}
  {self.formatter.colorize('$', 'green')} {self.prog} scikit-learn --pattern "^numpy|^scipy"
  
  {self.formatter.colorize('# Exclude optional and dev dependencies', 'dim')}
  {self.formatter.colorize('$', 'green')} {self.prog} django --no-optional --no-dev
  
  {self.formatter.colorize('# Linux-specific dependencies only', 'dim')}
  {self.formatter.colorize('$', 'green')} {self.prog} cryptography --platform linux

{self.formatter.colorize('Deduplication (NEW!):', 'cyan', bold=True)}
  {self.formatter.colorize('# Merge duplicate branches for cleaner output', 'dim')}
  {self.formatter.colorize('$', 'green')} {self.prog} pyputil --deduplicate --duplicate-handling merge
  
  {self.formatter.colorize('# Collapse duplicates with reference counts', 'dim')}
  {self.formatter.colorize('$', 'green')} {self.prog} tensorflow --deduplicate --duplicate-handling collapse
  
  {self.formatter.colorize('# Mark shared dependencies for analysis', 'dim')}
  {self.formatter.colorize('$', 'green')} {self.prog} django --deduplicate --duplicate-handling mark-shared
  
  {self.formatter.colorize('# Show all (disable deduplication)', 'dim')}
  {self.formatter.colorize('$', 'green')} {self.prog} numpy --duplicate-handling show-all

{self.formatter.colorize('Export Formats:', 'cyan', bold=True)}
  {self.formatter.colorize('# Export as JSON', 'dim')}
  {self.formatter.colorize('$', 'green')} {self.prog} numpy --format json --output numpy.json
  
  {self.formatter.colorize('# Generate interactive HTML report', 'dim')}
  {self.formatter.colorize('$', 'green')} {self.prog} pandas --format html --output pandas.html
  
  {self.formatter.colorize('# Create Graphviz visualization', 'dim')}
  {self.formatter.colorize('$', 'green')} {self.prog} flask --format dot --output flask.dot
  
  {self.formatter.colorize('# Generate Mermaid diagram', 'dim')}
  {self.formatter.colorize('$', 'green')} {self.prog} fastapi --format mermaid --output diagram.mmd

{self.formatter.colorize('Analysis:', 'cyan', bold=True)}
  {self.formatter.colorize('# Show statistics and conflicts', 'dim')}
  {self.formatter.colorize('$', 'green')} {self.prog} scipy --stats --conflicts
  
  {self.formatter.colorize('# Find missing packages', 'dim')}
  {self.formatter.colorize('$', 'green')} {self.prog} myapp --orphans --verbose
  
  {self.formatter.colorize('# Detailed analysis with all info', 'dim')}
  {self.formatter.colorize('$', 'green')} {self.prog} requests --stats --conflicts --orphans --verbose

{self.formatter.colorize('Pipeline Examples:', 'cyan', bold=True)}
  {self.formatter.colorize('# Analyze multiple packages', 'dim')}
  {self.formatter.colorize('$', 'green')} for pkg in requests pandas numpy; do
  {self.formatter.colorize('$', 'green')}     {self.prog} $pkg --depth 2 --format json --output ${{pkg}}.json
  {self.formatter.colorize('$', 'green')} done
  
  {self.formatter.colorize('# Generate requirements from analysis', 'dim')}
  {self.formatter.colorize('$', 'green')} {self.prog} myapp --no-optional --format json | jq '.dependencies[].name'

{self.formatter.colorize('Troubleshooting:', 'cyan', bold=True)}
  {self.formatter.colorize('# Debug mode with traceback', 'dim')}
  {self.formatter.colorize('$', 'green')} {self.prog} problematic-package --debug
  
  {self.formatter.colorize('# Verbose output for detailed logs', 'dim')}
  {self.formatter.colorize('$', 'green')} {self.prog} pandas --verbose --depth 3
"""
        return self._format_section("EXAMPLES", examples_text)
    
    def _format_exit_codes(self) -> str:
        """
        Format the exit codes section with error code documentation.
        
        Documents all possible exit codes that the application can return
        and their meanings. Exit codes help scripts and automation tools
        determine whether the operation succeeded or what type of failure
        occurred.
        
        Exit codes:
        - 0: Success - Tree generated successfully
        - 1: General error - Invalid arguments or runtime error
        - 2: Package not found - The specified package is not installed
        - 3: Import error - Required dependencies not available
        - 130: Interrupted by user (Ctrl+C) - handled separately
        
        Returns
        -------
        str
            Formatted exit codes section with color-coded codes and descriptions.
        """
        exit_codes_text = f"""
{self.formatter.colorize('0', 'green')}  Success - Tree generated successfully
{self.formatter.colorize('1', 'red')}   General error - Invalid arguments or runtime error
{self.formatter.colorize('2', 'yellow')} Package not found - The specified package is not installed
{self.formatter.colorize('3', 'yellow')} Import error - Required dependencies not available
"""
        return self._format_section("EXIT CODES", exit_codes_text)
    
    def _format_environment(self) -> str:
        """
        Format the environment variables section.
        
        Documents all environment variables that affect the tool's behavior.
        These allow users to configure default settings without repeatedly
        specifying command-line arguments.
        
        Environment variables:
        - PYPUTIL_NO_COLOR: Set to disable colored output (any value)
        - PYPUTIL_VERBOSE: Set to enable verbose output (any value)
        - PYPUTIL_CACHE_SIZE: Set cache size for package metadata (default: 1000)
        - PYPUTIL_DEDUPLICATE: Set default deduplication behavior ('true'/'false')
        - PYPUTIL_DUP_HANDLING: Set default duplicate handling strategy
        
        Returns
        -------
        str
            Formatted environment variables section with variable names
            in cyan and descriptions.
        """
        env_text = f"""
{self.formatter.colorize('PYPUTIL_NO_COLOR', 'cyan')}  Set to disable colored output (any value)
{self.formatter.colorize('PYPUTIL_VERBOSE', 'cyan')}    Set to enable verbose output (any value)
{self.formatter.colorize('PYPUTIL_CACHE_SIZE', 'cyan')} Set cache size for package metadata (default: 1000)
{self.formatter.colorize('PYPUTIL_DEDUPLICATE', 'cyan')} Set default deduplication behavior ('true'/'false')
{self.formatter.colorize('PYPUTIL_DUP_HANDLING', 'cyan')} Set default duplicate handling strategy
"""
        return self._format_section("ENVIRONMENT VARIABLES", env_text)
    
    def _format_footer(self) -> str:
        """
        Format the help footer with documentation links and support information.
        
        Creates a footer section with links to:
        - GitHub repository
        - Issue tracker
        - License information
        - Bug reporting instructions
        
        This provides users with next steps after reading the help text,
        such as where to report bugs or find more documentation.
        
        Returns
        -------
        str
            Formatted footer string with clickable-like links and information.
        """
        return f"""
{self.formatter.colorize('Documentation:', 'cyan', bold=True)}
  • GitHub: https://github.com/moamen-walid-pyputil/pyputil
  • Issues: https://github.com/moamen-walid-pyputil/pyputil/issues
  • License: MIT License

{self.formatter.colorize('Report bugs to:', 'cyan', bold=True)} https://github.com/moamen-walid-pyputil/pyputil/issues
"""


# =============================================================================
# MAIN CLI APPLICATION
# =============================================================================

class DependencyTreeCLI:
    """
    Main CLI application for dependency tree analysis.
    
    This class orchestrates the entire command-line interface, handling
    argument parsing, tree building, output formatting, and error management.
    It serves as the central coordinator that:
    
    1. Parses command-line arguments via CLIArgumentParser
    2. Validates user input and set up the environment
    3. Processes package analysis requests
    4. Exports results in various formats (text, JSON, YAML, HTML, DOT, Mermaid)
    5. Displays additional analysis (statistics, conflicts, orphans)
    6. Handles errors gracefully with appropriate exit codes
    
    The class is designed to be instantiated and run via the run() method,
    which accepts command-line arguments as a list of strings and returns
    an exit code suitable for sys.exit().
    
    Attributes
    ----------
    formatter : TerminalFormatter
        Terminal output formatter instance used for all styled output.
        Created at initialization and configured based on arguments.
    args : argparse.Namespace
        Parsed command-line arguments. Populated after parse_args() is
        called. Contains all user-specified options and flags.
    exit_code : int
        Application exit code. 0 for success, non-zero for errors.
        Updated during run() execution based on outcomes.
    
    Examples
    --------
    >>> cli = DependencyTreeCLI()
    >>> cli.run(["requests", "--depth", "2"])
    
    >>> cli = DependencyTreeCLI()
    >>> exit_code = cli.run(["--format", "json", "pandas"])
    """
    
    def __init__(self):
        """
        Initialize the CLI application.
        
        Creates a TerminalFormatter for styled output and initializes
        the args and exit_code attributes to their default values.
        The formatter is created with colorize=True by default, but this
        can be overridden later based on --no-color argument.
        """
        self.formatter = TerminalFormatter(colorize=True)
        self.args = None
        self.exit_code = 0
    
    def create_parser(self) -> CLIArgumentParser:
        """
        Create and configure the argument parser with all options.
        
        This method builds the complete CLIArgumentParser with all
        available command-line options organized into logical groups:
        
        1. Basic options:
           - package: Name of package to analyze (positional)
           - -v/--version: Version information
           - -d/--depth: Maximum recursion depth
           - --no-color: Disable colored output
           - --verbose/-V: Verbose output
           --quiet/-q: Suppress non-error output
           --debug: Debug mode with tracebacks
        
        2. Filter options:
           - --pattern: Regex pattern for filtering packages
           - --no-optional: Exclude optional dependencies
           - --no-dev/--no-development: Exclude development dependencies
           - --platform: Filter by platform (linux, windows, darwin, unix)
           - --python-version: Filter by Python version
           - --include-extras: Include specific extras groups
        
        3. Output options:
           - -f/--format: Output format (text, json, yaml, html, dot, mermaid)
           - -o/--output: Output file path
           - --show-extras: Display extras information
           - --show-markers: Display environment markers
           - --no-versions: Hide version numbers
           - --no-requirements: Hide requirement specifications
           - --stats: Show tree statistics
           - --conflicts: Show conflict detection results
           - --orphans: Show orphaned/missing packages
        
        4. Deduplication options:
           - --deduplicate: Enable shared dependency deduplication
           - --duplicate-handling: Strategy for duplicate handling
             (show-all, deduplicate, merge, mark-shared, collapse)
        
        5. Parallel processing:
           - -p/--parallel: Number of parallel threads
        
        Returns
        -------
        CLIArgumentParser
            Fully configured argument parser with all CLI options registered
            and ready to parse command-line arguments.
        """
        parser = CLIArgumentParser(
            prog="pyputil-tree",
            description=self._get_description(),
            epilog=self._get_epilog(),
            formatter_class=argparse.RawDescriptionHelpFormatter
        )
        
        # ================================================================
        # BASIC OPTIONS GROUP
        # ================================================================
        # Positional argument for the package name to analyze
        # nargs='?' makes this optional so help/version can run without it
        parser.add_argument('package', nargs='?', help='Package name to analyze')
        
        # Display version information and exit
        parser.add_argument('-v', '--version', action='store_true', help='Show version and exit')
        
        # Maximum recursion depth for dependency tree
        # Default is 1 (direct dependencies only). Use -1 for unlimited depth
        parser.add_argument('-d', '--depth', type=int, default=1, 
                           help='Maximum recursion depth (default: 1, -1 for unlimited)')
        
        # Disable colored output even if terminal supports it
        parser.add_argument('--no-color', action='store_true', help='Disable colored output')
        
        # Enable verbose output with extra diagnostic information
        parser.add_argument('--verbose', '-V', action='store_true', help='Enable verbose output')
        
        # Suppress all non-error output for quiet operation
        parser.add_argument('--quiet', '-q', action='store_true', help='Suppress non-error output')
        
        # Enable debug mode with full traceback on errors
        parser.add_argument('--debug', action='store_true', help='Enable debug mode')
        
        # ================================================================
        # FILTER OPTIONS GROUP
        # ================================================================
        # Regex pattern to filter displayed packages
        parser.add_argument('--pattern', type=str, help='Regex pattern to filter packages')
        
        # Exclude optional dependencies (marked with 'extra' or 'optional')
        parser.add_argument('--no-optional', action='store_true', help='Exclude optional dependencies')
        
        # Exclude development dependencies (--no-dev or --no-development)
        parser.add_argument('--no-dev', '--no-development', action='store_true', dest='no_dev',
                           help='Exclude development dependencies')
        
        # Filter dependencies by target platform
        parser.add_argument('--platform', choices=['linux', 'windows', 'darwin', 'unix'],
                           help='Filter by platform')
        
        # Filter dependencies by Python version requirement
        parser.add_argument('--python-version', type=str,
                           help='Filter by Python version (e.g., ">=3.8")')
        
        # Include specific extras groups
        parser.add_argument('--include-extras', type=str,
                           help='Comma-separated extras to include')
        
        # ================================================================
        # OUTPUT OPTIONS GROUP
        # ================================================================
        # Output format selection
        parser.add_argument('-f', '--format',
                           choices=['text', 'json', 'yaml', 'html', 'dot', 'mermaid'],
                           default='text',
                           help='Output format (default: text)')
        
        # Output file path (if not specified, output goes to stdout)
        parser.add_argument('-o', '--output', type=str, help='Write output to file')
        
        # Display package extras information
        parser.add_argument('--show-extras', action='store_true', help='Show package extras')
        
        # Display environment markers
        parser.add_argument('--show-markers', action='store_true', help='Show environment markers')
        
        # Hide package version numbers for cleaner display
        parser.add_argument('--no-versions', action='store_true', help='Hide package versions')
        
        # Hide version requirements from parent packages
        parser.add_argument('--no-requirements', action='store_true', help='Hide version requirements')
        
        # Include tree statistics in output
        parser.add_argument('--stats', action='store_true', help='Show tree statistics')
        
        # Check for and display version conflicts
        parser.add_argument('--conflicts', action='store_true', help='Show conflict detection')
        
        # Check for and display orphaned (missing) packages
        parser.add_argument('--orphans', action='store_true', help='Show orphaned packages')
        
        # ================================================================
        # DEDUPLICATION OPTIONS GROUP (NEW!)
        # ================================================================
        # Master switch for shared dependency deduplication
        parser.add_argument('--deduplicate', action='store_true',
                           help='Enable deduplication of shared dependencies')
        
        # Strategy for handling duplicate dependencies
        parser.add_argument('--duplicate-handling',
                           choices=['show-all', 'deduplicate', 'merge', 'mark-shared', 'collapse'],
                           default='deduplicate',
                           help='Strategy for handling duplicate dependencies (default: deduplicate)')
        
        # ================================================================
        # PARALLEL PROCESSING OPTIONS GROUP
        # ================================================================
        # Number of parallel threads for processing
        parser.add_argument('-p', '--parallel', type=int, default=1,
                           help='Number of parallel threads (default: 1)')
        
        return parser
    
    def _get_description(self) -> str:
        """
        Get program description text for the help output.
        
        Returns a multi-line string describing the tool's purpose and
        key features including the new deduplication capabilities.
        This text appears in the help output under the DESCRIPTION section.
        
        Returns
        -------
        str
            Program description with feature list, formatted for help output.
        """
        return """
        Analyze and visualize Python package dependencies with rich terminal output,
        multiple export formats, and advanced filtering capabilities.
        
        Features:
          • Recursive dependency tree generation
          • Cycle detection and conflict analysis
          • Multiple output formats (text, JSON, YAML, HTML, Graphviz, Mermaid)
          • Platform and Python version filtering
          • **NEW** Shared dependency deduplication (merge, collapse, or mark)
          • Parallel processing for large trees
          • Beautiful terminal output with colors
        """
    
    def _get_epilog(self) -> str:
        """
        Get program epilog text for the help output.
        
        Returns text displayed at the end of the help output, providing
        quick examples and a link for more information. This helps users
        get started quickly without reading the entire documentation.
        
        Returns
        -------
        str
            Epilog text with examples and reference link.
        """
        return """
        Examples:
          pyputil-tree requests
          pyputil-tree pandas --depth 3
          pyputil-tree numpy --format json --output tree.json
          pyputil-tree scikit-learn --pattern "^numpy|^scipy" --depth 2
          pyputil-tree pyputil --deduplicate --duplicate-handling merge
        
        For more information, visit: https://github.com/moamen-walid-pyputil/pyputil
        """
    
    def parse_args(self, argv: List[str]) -> argparse.Namespace:
        """
        Parse command-line arguments with special handling for help/version.
        
        This method handles argument parsing including special cases
        for --help and --version flags, which can be invoked without
        specifying a package name.
        
        Behavior:
        - If no arguments are provided, show help and exit
        - If only --help/-h is provided, show help and exit
        - If only --version/-v is provided, show version and exit
        - Otherwise, parse arguments normally
        
        The method also converts the duplicate-handling string to an enum
        value for use by the tree builder and printer.
        
        Parameters
        ----------
        argv : List[str]
            Command-line arguments as a list of strings, typically from
            sys.argv[1:]. Should not include the program name (argv[0]).
        
        Returns
        -------
        argparse.Namespace
            Parsed arguments object with attributes for all CLI options.
            The returned object includes an additional attribute:
            duplicate_handling_enum: The enum value for duplicate handling.
        
        Raises
        ------
        SystemExit
            If --help or --version is requested, exits with code 0 after
            displaying the requested information.
        """
        parser = self.create_parser()
        
        # Handle empty arguments or help flag
        if len(argv) == 0 or (len(argv) == 1 and argv[0] in ['-h', '--help']):
            parser.print_help()
            sys.exit(0)
        
        # Handle version flag
        if len(argv) == 1 and argv[0] in ['-v', '--version']:
            print(f"pyputil-tree version {__version__}")
            sys.exit(0)
        
        # Parse all arguments normally
        args = parser.parse_args(argv)
        
        # Convert duplicate-handling string to enum value for passing to builder
        # This mapping is used when calling get_tree or print_tree
        handling_map = {
            'show-all': 'show_all',
            'deduplicate': 'deduplicate',
            'merge': 'merge',
            'mark-shared': 'mark_shared',
            'collapse': 'collapse'
        }
        args.duplicate_handling_enum = handling_map.get(args.duplicate_handling, 'deduplicate')
        
        return args
    
    def _setup_environment(self) -> None:
        """
        Setup runtime environment based on parsed arguments.
        
        This method applies the user-specified argument settings to
        the runtime environment:
        - Disables color output if --no-color was specified
        - Prints verbose mode notification if --verbose was specified
        - Prints debug mode notification if --debug was specified
        
        It also checks environment variables for default deduplication
        settings if the corresponding CLI arguments were not provided:
        - PYPUTIL_DEDUPLICATE: Set to 'true', '1', or 'yes' to enable deduplication
        - PYPUTIL_DUP_HANDLING: Set default duplicate handling strategy
        
        Returns
        -------
        None
            This method modifies instance state but does not return a value.
        """
        # Disable color if --no-color flag was set
        if self.args.no_color:
            self.formatter.use_colorize = False
        
        # Print verbose mode notification if enabled
        if self.args.verbose:
            print(self.formatter.info("Verbose mode enabled"))
        
        # Print debug mode notification if enabled
        if self.args.debug:
            print(self.formatter.debug("Debug mode enabled"))
        
        # Check environment variables for deduplication defaults
        if not self.args.deduplicate:
            env_dedup = os.environ.get('PYPUTIL_DEDUPLICATE', '').lower()
            if env_dedup in ('true', '1', 'yes'):
                self.args.deduplicate = True
                if self.args.verbose:
                    print(self.formatter.debug("Deduplication enabled via environment variable"))
        
        # Report deduplication settings in verbose mode
        if self.args.deduplicate and self.args.verbose:
            print(self.formatter.info(f"Deduplication strategy: {self.args.duplicate_handling}"))
    
    def _process_package(self, package_name: str) -> Optional[Union[str, Dict]]:
        """
        Process the package and build dependency tree with deduplication support.
        
        This method now includes deduplication parameters when calling the
        tree building functions.
        
        Parameters
        ----------
        package_name : str
            Name of the Python package to analyze.
        
        Returns
        -------
        Optional[Union[str, Dict]]
            For text format: Returns True/False success indicator.
            For JSON/YAML formats: Returns the tree data structure.
            Returns None if processing fails.
        """
        # Handle max_depth=-1 as unlimited depth
        max_depth = self.args.depth if self.args.depth != -1 else None
        
        # Handle text format output (direct to terminal)
        if self.args.format == 'text':
            import re
            # Compile regex pattern if provided
            pattern = re.compile(self.args.pattern) if self.args.pattern else None
            
            # Call print_tree with all options including deduplication
            success = print_tree(
                package_name,
                max_depth=max_depth,
                pattern_filter=pattern,
                skip_optional=self.args.no_optional,
                skip_development=self.args.no_dev,
                parallel_processing=self.args.parallel,
                show_extras=self.args.show_extras,
                show_markers=self.args.show_markers,
                show_versions=not self.args.no_versions,
                show_required=not self.args.no_requirements,
                colorize=not self.args.no_color,
                # Deduplication parameters
                deduplicate_shared=self.args.deduplicate,
                duplicate_handling=self.args.duplicate_handling_enum
            )
            
            return success
        
        # Handle structured output formats (JSON, YAML, dict)
        output_format_map = {
            'json': 'json',
            'yaml': 'yaml',
            'dict': 'dict'
        }
        
        # Parse include-extras argument into a list
        include_extras = None
        if self.args.include_extras:
            include_extras = [e.strip() for e in self.args.include_extras.split(',')]
        
        # Call get_tree with all options including deduplication
        tree = get_tree(
            package_name,
            max_depth=max_depth,
            output_format=output_format_map.get(self.args.format, 'dict'),
            skip_optional=self.args.no_optional,
            skip_development=self.args.no_dev,
            parallel_processing=self.args.parallel,
            platform_filter=self.args.platform,
            python_version_filter=self.args.python_version,
            include_extras=include_extras,
            include_stats=self.args.stats,
            # Deduplication parameters
            deduplicate_shared=self.args.deduplicate,
            duplicate_handling=self.args.duplicate_handling_enum
        )
        
        return tree
    
    def _export_visualization(self, package_name: str) -> bool:
        """
        Export tree to visualization format using the new printer system.
        
        This method uses DependencyTreePrinter to export dependency trees
        to visualization formats (HTML, DOT, Mermaid) with full support for
        deduplication features.
        
        Parameters
        ----------
        package_name : str
            Package name to analyze and export.
        
        Returns
        -------
        bool
            True if export was successful, False otherwise.
        """
        # Generate output filename
        output_file = self.args.output or f"{package_name}_tree.{self.args.format}"
        
        try:
            # Create a printer instance with deduplication settings
            printer = DependencyTreePrinter(
                deduplicate_shared=self.args.deduplicate,
                duplicate_handling=self.args.duplicate_handling_enum,
                max_depth=self.args.depth if self.args.depth != -1 else None,
                skip_optional=self.args.no_optional,
                parallel_processing=self.args.parallel
            )
            
            # Map CLI format to TreeOutputFormat enum
            format_map = {
                'html': TreeOutputFormat.HTML,
                'dot': TreeOutputFormat.DOT,
                'mermaid': TreeOutputFormat.MERMAID
            }
            
            output_format = format_map.get(self.args.format)
            if not output_format:
                return False
            
            # Export using the printer
            printer.export_tree(package_name, output_format, output_file)
            
            # Print success message unless quiet mode
            if not self.args.quiet:
                print(self.formatter.success(f"Exported to {output_file}"))
            return True
            
        except Exception as e:
            # Show detailed error in debug mode
            if self.args.debug:
                import traceback
                traceback.print_exc()
            print(self.formatter.error(f"Export failed: {e}"))
            return False
    
    def _show_analysis(self, tree: Dict) -> None:
        """
        Show additional analysis results (stats, conflicts, orphans).
        
        This method displays supplementary analysis information based
        on the user's requested options:
        - Stats: Tree metrics (total packages, depth, circular dependencies)
        - Conflicts: Version conflicts between different requirements
        - Orphans: Packages that are missing or not installed
        
        The results are displayed using the formatter's print_summary()
        and styled warning/success messages for clean presentation.
        
        Parameters
        ----------
        tree : Dict
            Tree dictionary containing the complete dependency structure.
            Must be the raw dict format (not JSON/YAML string) for the
            analysis functions to process correctly.
        
        Returns
        -------
        None
            This method prints directly to stdout and does not return a value.
        """
        # Display tree statistics if requested
        if self.args.stats:
            stats = calculate_tree_metrics(tree)
            
            # Add deduplication stats if available
            dedup_stats = {}
            if self.args.deduplicate and 'statistics' in tree:
                dedup_stats = {
                    'shared dependencies': tree['statistics'].get('shared_dependencies', 0),
                    'deduplications saved': tree['statistics'].get('deduplications_saved', 0)
                }
            
            all_stats = {
                'total packages': stats.get('total_packages', 0),
                'unique packages': stats.get('unique_packages', 0),
                'max depth': stats.get('max_depth', 0),
                'average depth': f"{stats.get('average_depth', 0):.2f}",
                'circular dependencies': stats.get('circular_dependencies', 0)
            }
            
            if dedup_stats:
                all_stats.update(dedup_stats)
            
            self.formatter.print_summary("Tree Statistics", all_stats)
        
        # Display version conflicts if requested
        if self.args.conflicts:
            conflicts = find_conflicts(tree)
            if conflicts:
                print(self.formatter.header("Conflicts Detected", level=2))
                for pkg, info in conflicts.items():
                    print(self.formatter.warning(f"  {pkg}: {info.get('different_versions', [])}"))
            else:
                print(self.formatter.success("No conflicts detected"))
        
        # Display orphaned packages if requested
        if self.args.orphans:
            orphans = find_orphaned_packages(tree)
            if orphans:
                print(self.formatter.header("Orphaned Packages", level=2))
                for pkg in orphans:
                    print(self.formatter.warning(f"  {pkg}"))
            else:
                print(self.formatter.success("No orphaned packages found"))
    
    def run(self, argv: List[str] = None) -> int:
        """
        Run the CLI application.
        
        This is the main entry point for the application. It orchestrates
        the complete workflow:
        1. Parse command-line arguments
        2. Validate that a package name was provided
        3. Check that imports succeeded
        4. Set up the environment (colors, verbosity)
        5. Process the package analysis
        6. Handle output in the requested format
        7. Show additional analysis if requested
        8. Return appropriate exit code
        
        The method handles KeyboardInterrupt gracefully and catches
        all exceptions for clean error reporting.
        
        Parameters
        ----------
        argv : List[str], optional
            Command-line arguments as a list of strings. If None,
            defaults to sys.argv[1:] (command-line arguments excluding
            the program name). Can be provided explicitly for testing.
        
        Returns
        -------
        int
            Exit code indicating success or failure:
            - 0: Success
            - 1: General error (argument parsing, runtime error)
            - 2: Package not found
            - 3: Import error (pyputil.tree not available)
            - 130: Interrupted by user (Ctrl+C)
        """
        # Use sys.argv[1:] if no arguments provided
        if argv is None:
            argv = sys.argv[1:]
        
        # Parse command-line arguments
        try:
            self.args = self.parse_args(argv)
        except SystemExit as e:
            return e.code if hasattr(e, 'code') else 0
        except Exception as e:
            print(self.formatter.error(f"Argument parsing error: {e}"))
            return 1
        
        # Validate that a package name was provided
        if not self.args.package:
            print(self.formatter.error("Package name is required"))
            print(self.formatter.info("Usage: pyputil-tree <package_name> [options]"))
            print(self.formatter.info("Try 'pyputil-tree --help' for more information"))
            return 1
        
        # Check that the pyputil.tree library was imported successfully
        if not IMPORT_SUCCESS:
            print(self.formatter.error(f"Failed to import pyputil.tree: {IMPORT_ERROR}"))
            return 3
        
        # Apply environment settings from parsed arguments
        self._setup_environment()
        
        # Print banner and analysis info in verbose mode
        if self.args.verbose and not self.args.quiet:
            self.formatter.print_banner()
            print(self.formatter.info(f"Analyzing package: {self.args.package}"))
        
        # Process the package analysis
        try:
            result = self._process_package(self.args.package)
            
            # Check if processing failed
            if result is None or (isinstance(result, bool) and not result):
                print(self.formatter.error(f"Failed to analyze package: {self.args.package}"))
                return 2
            
            # Handle output based on requested format
            if self.args.format in ['html', 'dot', 'mermaid']:
                # Export visualization using new printer system
                if self._export_visualization(self.args.package):
                    # Get tree for analysis display
                    tree = get_tree(
                        self.args.package,
                        max_depth=self.args.depth if self.args.depth != -1 else None,
                        output_format='dict',
                        deduplicate_shared=self.args.deduplicate,
                        duplicate_handling=self.args.duplicate_handling_enum
                    )
                    if tree:
                        self._show_analysis(tree)
                else:
                    return 2
                    
            elif self.args.format == 'text':
                # Text format was already printed by print_tree()
                # If --output was specified, capture and write to file
                if self.args.output:
                    import io
                    from contextlib import redirect_stdout
                    
                    output_buffer = io.StringIO()
                    with redirect_stdout(output_buffer):
                        self._process_package(self.args.package)
                    
                    output_content = output_buffer.getvalue()
                    with open(self.args.output, 'w', encoding='utf-8') as f:
                        f.write(output_content)
                    
                    if not self.args.quiet:
                        print(self.formatter.success(f"Output written to {self.args.output}"))
            else:
                # Handle structured output formats (JSON, YAML)
                output_text = result if isinstance(result, str) else json.dumps(result, indent=2, default=str)
                
                if self.args.output:
                    with open(self.args.output, 'w', encoding='utf-8') as f:
                        if isinstance(output_text, str):
                            f.write(output_text)
                        else:
                            json.dump(output_text, f, indent=4)
                    if not self.args.quiet:
                        print(self.formatter.success(f"Output written to {self.args.output}"))
                else:
                    print(output_text)
            
            return 0
            
        except KeyboardInterrupt:
            # Handle Ctrl+C gracefully
            print(self.formatter.warning("\nInterrupted by user"))
            return 130
        except Exception as e:
            # Handle all other exceptions
            # In debug mode, show full traceback
            if self.args.debug:
                import traceback
                traceback.print_exc()
            else:
                self.formatter.print_error_detail(e, context=f"Analyzing {self.args.package}")
            return 1


# =============================================================================
# ENTRY POINT
# =============================================================================

def main():
    """
    Main entry point for the CLI application.
    
    This function serves as the console_scripts entry point defined
    in setup.py/pyproject.toml. It creates a DependencyTreeCLI instance
    and runs it with sys.argv[1:] (command-line arguments). The return
    value from run() is passed to sys.exit() to set the process exit code.
    
    This function is also used when the module is run directly:
        python -m pyputil.tree.cli
    
    The separation of main() from the class allows both script entry
    points and direct module execution to work identically.
    
    Returns
    -------
    None
        This function calls sys.exit() and does not return.
    
    Examples
    --------
    >>> if __name__ == "__main__":
    ...     main()
    """
    cli = DependencyTreeCLI()
    sys.exit(cli.run())


# =============================================================================
# SCRIPT EXECUTION
# =============================================================================

# Run main() when the module is executed directly
# This allows the file to be run as: python cli.py
# The __name__ == "__main__" check is the standard Python idiom
# for making a file both importable and directly executable.
if __name__ == "__main__":
    main()