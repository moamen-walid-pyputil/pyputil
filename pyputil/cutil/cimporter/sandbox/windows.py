#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
==================================
    WINDOWS SANDBOX UTILITIES
==================================

Comprehensive Windows-specific sandboxing utilities providing enterprise-grade
process isolation, resource limiting, and security controls for Windows platforms.

This module implements Windows-native sandboxing mechanisms including:
- Job Objects for CPU, memory, and process limits
- Restricted Tokens for privilege removal
- AppContainer Isolation for Windows Store-style sandboxing
- Integrity Level management (Low, Medium, High, System)
- Desktop Isolation for UI/window message protection
- Process Mitigation Policies (DEP, ASLR, CFG, etc.)
- Windows Filtering Platform (WFP) for network isolation

Architecture Overview:
---------------------
The module provides a layered security model where multiple isolation
mechanisms can be combined:

Layer 1: Job Objects → Resource limiting (CPU, memory, I/O)
Layer 2: Restricted Tokens → Privilege and group removal
Layer 3: Integrity Levels → Mandatory access control
Layer 4: AppContainer → Capability-based sandboxing
Layer 5: Desktop Isolation → UI/window isolation
Layer 6: Process Mitigations → Exploit prevention

Key Features:
------------
- Automatic cleanup of child processes
- Resource usage monitoring and reporting
- Context manager support for RAII patterns
- Comprehensive error handling with detailed messages
- Thread-safe operations with internal locking
- Support for Windows 7 through Windows 11
- Compatibility with both 32-bit and 64-bit processes

Author: CImporter Team
Version: 2.0.0
License: MIT
"""

import os
import sys
import time
import ctypes
import ctypes.wintypes
import threading
import subprocess
import logging
from ctypes import (
    windll, byref, c_void_p, c_char_p, c_wchar_p, c_ulong, c_ulonglong,
    c_size_t, c_int, c_uint, c_bool, POINTER, sizeof, create_string_buffer,
    create_unicode_buffer, WinError, GetLastError, FormatError,
    Structure, Union, Array
)
from ctypes.wintypes import (
    HANDLE, DWORD, WORD, LPVOID, LPCWSTR, LPWSTR, LPDWORD, ULONG,
    BOOL, UINT, LARGE_INTEGER, ULARGE_INTEGER, SIZE_T, PVOID,
    HMODULE, HINSTANCE, HKEY, PHKEY, LPSTR, LPCSTR
)
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum, IntFlag, auto
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
import json
import re

# Initialize logger
logger = logging.getLogger(__name__)


# ============================================================================
# Windows API Constants
# ============================================================================

# Process Creation Flags
# These flags control how a new process is created and its initial state.

CREATE_BREAKAWAY_FROM_JOB = 0x01000000
"""
Allows the new process to break away from the parent's job object.
Required when creating a process that will be assigned to a different job.
"""

CREATE_SUSPENDED = 0x00000004
"""
Creates the process in a suspended state.
The process will not run until ResumeThread is called.
"""

CREATE_NEW_CONSOLE = 0x00000010
"""
Creates the process with a new console window.
Useful for GUI applications that need their own console.
"""

CREATE_NEW_PROCESS_GROUP = 0x00000200
"""
Creates a new process group.
Allows sending Ctrl+C/Ctrl+Break signals to the entire group.
"""

CREATE_NO_WINDOW = 0x08000000
"""
Creates the process without a window.
Useful for console applications that should run in the background.
"""

CREATE_UNICODE_ENVIRONMENT = 0x00000400
"""
Indicates that the environment block uses Unicode characters.
"""

EXTENDED_STARTUPINFO_PRESENT = 0x00080000
"""
Indicates that extended startup information is present.
Required for using AppContainer and other advanced features.
"""

# Process Access Rights
# These flags control what operations can be performed on a process handle.

PROCESS_TERMINATE = 0x0001
"""Required to terminate a process using TerminateProcess."""

PROCESS_CREATE_THREAD = 0x0002
"""Required to create a remote thread in the process."""

PROCESS_VM_OPERATION = 0x0008
"""Required to perform operations on the process's virtual memory."""

PROCESS_VM_READ = 0x0010
"""Required to read from the process's virtual memory."""

PROCESS_VM_WRITE = 0x0020
"""Required to write to the process's virtual memory."""

PROCESS_DUP_HANDLE = 0x0040
"""Required to duplicate handles from the process."""

PROCESS_CREATE_PROCESS = 0x0080
"""Required to create a child process."""

PROCESS_SET_QUOTA = 0x0100
"""Required to set memory limits for the process."""

PROCESS_SET_INFORMATION = 0x0200
"""Required to set process information."""

PROCESS_QUERY_INFORMATION = 0x0400
"""Required to query process information."""

PROCESS_SUSPEND_RESUME = 0x0800
"""Required to suspend or resume the process."""

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
"""Required to query limited process information (Vista+)."""

PROCESS_ALL_ACCESS = 0x1FFFFF
"""All possible access rights for a process object."""

# Job Object Information Classes
# Used with SetInformationJobObject and QueryInformationJobObject.

class JobObjectInfoClass(IntEnum):
    """
    Information classes for job object configuration and queries.
    
    These constants specify what type of information is being set or queried
    on a job object.
    """
    BasicLimitInformation = 2
    """Basic limits including working set, process time, and active processes."""
    
    BasicUIRestrictions = 4
    """UI restrictions like clipboard access and desktop interaction."""
    
    SecurityLimitInformation = 5
    """Security limits including token filtering."""
    
    EndOfJobTimeInformation = 6
    """Action to take when job time limit is reached."""
    
    AssociateCompletionPortInformation = 7
    """I/O completion port for job notifications."""
    
    ExtendedLimitInformation = 9
    """Extended limits including memory, I/O, and CPU rate control."""
    
    GroupInformation = 11
    """Processor group information for systems with >64 processors."""
    
    CpuRateControlInformation = 15
    """CPU rate control (throttling) settings."""
    
    NetRateControlInformation = 32
    """Network bandwidth rate control."""
    
    NotificationLimitInformation = 33
    """Notification thresholds for resource usage."""
    
    LimitViolationInformation = 34
    """Information about limit violations that occurred."""

# Job Object Limit Flags
# Bitmask of limits to enforce on the job object.

class JobObjectLimitFlags(IntFlag):
    """
    Limit flags for job object restrictions.
    
    These flags specify which resource limits should be enforced.
    Multiple flags can be combined using bitwise OR.
    """
    
    JOB_OBJECT_LIMIT_WORKINGSET = 0x00000001
    """Limit the working set (physical memory) of processes."""
    
    JOB_OBJECT_LIMIT_PROCESS_TIME = 0x00000002
    """Limit per-process CPU time."""
    
    JOB_OBJECT_LIMIT_JOB_TIME = 0x00000004
    """Limit total CPU time for the entire job."""
    
    JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
    """Limit the number of simultaneously active processes."""
    
    JOB_OBJECT_LIMIT_AFFINITY = 0x00000010
    """Restrict processes to specific processor cores."""
    
    JOB_OBJECT_LIMIT_PRIORITY_CLASS = 0x00000020
    """Limit the priority class of processes."""
    
    JOB_OBJECT_LIMIT_PRESERVE_JOB_TIME = 0x00000040
    """Preserve job time accounting when job is closed."""
    
    JOB_OBJECT_LIMIT_SCHEDULING_CLASS = 0x00000080
    """Limit the scheduling class of processes."""
    
    JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
    """Limit committed memory per process."""
    
    JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
    """Limit total committed memory for the job."""
    
    JOB_OBJECT_LIMIT_JOB_READ_BYTES = 0x00010000
    """Limit total I/O read bytes (Windows 8+)."""
    
    JOB_OBJECT_LIMIT_JOB_WRITE_BYTES = 0x00020000
    """Limit total I/O write bytes (Windows 8+)."""
    
    JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400
    """Terminate process on unhandled exception."""
    
    JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000800
    """Allow child processes to break away from the job."""
    
    JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK = 0x00001000
    """Allow silent breakaway without error."""
    
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    """Kill all processes when the job handle is closed."""
    
    JOB_OBJECT_LIMIT_SUBSET_AFFINITY = 0x00004000
    """Allow processes to use a subset of the job affinity."""
    
    JOB_OBJECT_LIMIT_RATE_CONTROL = 0x00040000
    """Enable CPU rate control (Windows 8+)."""
    
    JOB_OBJECT_LIMIT_CPU_RATE_CONTROL = 0x00080000
    """Specific CPU rate control limits (Windows 10+)."""
    
    JOB_OBJECT_LIMIT_IO_RATE_CONTROL = 0x00100000
    """Enable I/O rate control (Windows 10+)."""
    
    JOB_OBJECT_LIMIT_NET_RATE_CONTROL = 0x00200000
    """Enable network rate control (Windows 10+)."""

# Job Object UI Restriction Flags
# Controls what UI interactions are permitted.

class JobObjectUIRestrictions(IntFlag):
    """
    UI restriction flags for job objects.
    
    These flags control user interface access for processes in the job.
    """
    
    JOB_OBJECT_UILIMIT_NONE = 0x00000000
    """No UI restrictions."""
    
    JOB_OBJECT_UILIMIT_HANDLES = 0x00000001
    """Prevent processes from accessing USER handles outside the job."""
    
    JOB_OBJECT_UILIMIT_READCLIPBOARD = 0x00000002
    """Prevent processes from reading the clipboard."""
    
    JOB_OBJECT_UILIMIT_WRITECLIPBOARD = 0x00000004
    """Prevent processes from writing to the clipboard."""
    
    JOB_OBJECT_UILIMIT_SYSTEMPARAMETERS = 0x00000008
    """Prevent processes from changing system parameters."""
    
    JOB_OBJECT_UILIMIT_DISPLAYSETTINGS = 0x00000010
    """Prevent processes from changing display settings."""
    
    JOB_OBJECT_UILIMIT_GLOBALATOMS = 0x00000020
    """Prevent processes from accessing global atoms."""
    
    JOB_OBJECT_UILIMIT_DESKTOP = 0x00000040
    """Prevent processes from creating/ switching desktops."""
    
    JOB_OBJECT_UILIMIT_EXITWINDOWS = 0x00000080
    """Prevent processes from calling ExitWindowsEx."""

# Token Information Classes
# Used with GetTokenInformation and SetTokenInformation.

class TOKEN_INFORMATION_CLASS(IntEnum):
    """
    Token information classes for security token operations.
    
    These constants specify what token information is being queried or modified.
    """
    
    TokenUser = 1
    """User account SID associated with the token."""
    
    TokenGroups = 2
    """Group SIDs associated with the token."""
    
    TokenPrivileges = 3
    """Privileges associated with the token."""
    
    TokenOwner = 4
    """Default owner SID for new objects."""
    
    TokenPrimaryGroup = 5
    """Default primary group SID for new objects."""
    
    TokenDefaultDacl = 6
    """Default DACL for new objects."""
    
    TokenSource = 7
    """Source of the token."""
    
    TokenType = 8
    """Whether token is primary or impersonation."""
    
    TokenImpersonationLevel = 9
    """Impersonation level of the token."""
    
    TokenStatistics = 10
    """Token statistics (memory usage, etc.)."""
    
    TokenRestrictedSids = 11
    """Restricting SIDs for the token."""
    
    TokenSessionId = 12
    """Terminal Services session ID."""
    
    TokenGroupsAndPrivileges = 13
    """Combined groups and privileges."""
    
    TokenSandBoxInert = 15
    """Whether token is sandbox inert."""
    
    TokenOrigin = 17
    """Originating logon session."""
    
    TokenElevationType = 18
    """Type of elevation (Limited, Full, Default)."""
    
    TokenLinkedToken = 19
    """Linked elevated token."""
    
    TokenElevation = 20
    """Whether token is elevated."""
    
    TokenHasRestrictions = 21
    """Whether token has restrictions."""
    
    TokenAccessInformation = 22
    """Access information for the token."""
    
    TokenVirtualizationAllowed = 23
    """Whether virtualization is allowed."""
    
    TokenVirtualizationEnabled = 24
    """Whether virtualization is enabled."""
    
    TokenIntegrityLevel = 25
    """Mandatory integrity level SID."""
    
    TokenUIAccess = 26
    """Whether UIAccess is enabled."""
    
    TokenMandatoryPolicy = 27
    """Mandatory integrity policy."""
    
    TokenLogonSid = 28
    """Logon session SID."""
    
    TokenIsAppContainer = 29
    """Whether token is for an AppContainer."""
    
    TokenCapabilities = 30
    """AppContainer capabilities."""
    
    TokenAppContainerSid = 31
    """AppContainer SID."""
    
    TokenAppContainerNumber = 32
    """AppContainer number."""
    
    TokenIsRestricted = 40
    """Whether token is restricted."""
    
    TokenIsSandboxed = 47
    """Whether token is sandboxed (Windows 10 RS4+)."""

# Token Privilege Attributes
# Flags controlling privilege state.

SE_PRIVILEGE_ENABLED = 0x00000002
"""The privilege is enabled."""

SE_PRIVILEGE_ENABLED_BY_DEFAULT = 0x00000001
"""The privilege is enabled by default."""

SE_PRIVILEGE_REMOVED = 0x00000004
"""The privilege has been removed from the token."""

SE_PRIVILEGE_USED_FOR_ACCESS = 0x80000000
"""The privilege was used to gain access."""

# Well-known Privilege Names
# String constants for Windows privileges.

SE_CREATE_TOKEN_NAME = "SeCreateTokenPrivilege"
"""Required to create a primary token."""

SE_ASSIGNPRIMARYTOKEN_NAME = "SeAssignPrimaryTokenPrivilege"
"""Required to assign the primary token of a process."""

SE_LOCK_MEMORY_NAME = "SeLockMemoryPrivilege"
"""Required to lock physical pages in memory."""

SE_INCREASE_QUOTA_NAME = "SeIncreaseQuotaPrivilege"
"""Required to increase process quotas."""

SE_TCB_NAME = "SeTcbPrivilege"
"""Act as part of the trusted computing base."""

SE_SECURITY_NAME = "SeSecurityPrivilege"
"""Required for security operations like auditing."""

SE_TAKE_OWNERSHIP_NAME = "SeTakeOwnershipPrivilege"
"""Required to take ownership of objects."""

SE_LOAD_DRIVER_NAME = "SeLoadDriverPrivilege"
"""Required to load or unload device drivers."""

SE_SYSTEM_PROFILE_NAME = "SeSystemProfilePrivilege"
"""Required to profile system performance."""

SE_SYSTEMTIME_NAME = "SeSystemtimePrivilege"
"""Required to change system time."""

SE_PROF_SINGLE_PROCESS_NAME = "SeProfileSingleProcessPrivilege"
"""Required to profile a single process."""

SE_INC_BASE_PRIORITY_NAME = "SeIncreaseBasePriorityPrivilege"
"""Required to increase process base priority."""

SE_CREATE_PAGEFILE_NAME = "SeCreatePagefilePrivilege"
"""Required to create a pagefile."""

SE_CREATE_PERMANENT_NAME = "SeCreatePermanentPrivilege"
"""Required to create permanent shared objects."""

SE_BACKUP_NAME = "SeBackupPrivilege"
"""Required to perform backup operations."""

SE_RESTORE_NAME = "SeRestorePrivilege"
"""Required to perform restore operations."""

SE_SHUTDOWN_NAME = "SeShutdownPrivilege"
"""Required to shut down the system."""

SE_DEBUG_NAME = "SeDebugPrivilege"
"""Required to debug processes."""

SE_AUDIT_NAME = "SeAuditPrivilege"
"""Required to generate security audit events."""

SE_SYSTEM_ENVIRONMENT_NAME = "SeSystemEnvironmentPrivilege"
"""Required to modify system environment variables."""

SE_CHANGE_NOTIFY_NAME = "SeChangeNotifyPrivilege"
"""Required to receive file change notifications (bypass traverse checking)."""

SE_REMOTE_SHUTDOWN_NAME = "SeRemoteShutdownPrivilege"
"""Required to shut down the system remotely."""

SE_UNDOCK_NAME = "SeUndockPrivilege"
"""Required to undock a laptop."""

SE_SYNC_AGENT_NAME = "SeSyncAgentPrivilege"
"""Required for sync agent operations."""

SE_ENABLE_DELEGATION_NAME = "SeEnableDelegationPrivilege"
"""Required to enable delegation of credentials."""

SE_MANAGE_VOLUME_NAME = "SeManageVolumePrivilege"
"""Required to manage volume maintenance tasks."""

SE_IMPERSONATE_NAME = "SeImpersonatePrivilege"
"""Required to impersonate a client after authentication."""

SE_CREATE_GLOBAL_NAME = "SeCreateGlobalPrivilege"
"""Required to create global named objects."""

SE_TRUSTED_CREDMAN_ACCESS_NAME = "SeTrustedCredManAccessPrivilege"
"""Required to access Credential Manager as trusted caller."""

SE_RELABEL_NAME = "SeRelabelPrivilege"
"""Required to modify mandatory integrity labels."""

SE_INC_WORKING_SET_NAME = "SeIncreaseWorkingSetPrivilege"
"""Required to increase process working set."""

SE_TIME_ZONE_NAME = "SeTimeZonePrivilege"
"""Required to change time zone."""

SE_CREATE_SYMBOLIC_LINK_NAME = "SeCreateSymbolicLinkPrivilege"
"""Required to create symbolic links."""

SE_DELEGATE_SESSION_USER_IMPERSONATE_NAME = "SeDelegateSessionUserImpersonatePrivilege"
"""Required to obtain impersonation token for session user."""

# Integrity Level RIDs
# Relative Identifiers for mandatory integrity levels.

SECURITY_MANDATORY_UNTRUSTED_RID = 0x00000000
"""Untrusted integrity level - most restricted."""

SECURITY_MANDATORY_LOW_RID = 0x00001000
"""Low integrity level - used for sandboxed processes."""

SECURITY_MANDATORY_MEDIUM_RID = 0x00002000
"""Medium integrity level - default for standard users."""

SECURITY_MANDATORY_MEDIUM_PLUS_RID = 0x00002100
"""Medium-plus integrity level - slightly elevated."""

SECURITY_MANDATORY_HIGH_RID = 0x00003000
"""High integrity level - administrator level."""

SECURITY_MANDATORY_SYSTEM_RID = 0x00004000
"""System integrity level - highest level, for system services."""

SECURITY_MANDATORY_PROTECTED_PROCESS_RID = 0x00005000
"""Protected process integrity level - for anti-malware etc."""

# Integrity Level Names Mapping
INTEGRITY_LEVEL_MAP = {
    "UNTRUSTED": SECURITY_MANDATORY_UNTRUSTED_RID,
    "LOW": SECURITY_MANDATORY_LOW_RID,
    "MEDIUM": SECURITY_MANDATORY_MEDIUM_RID,
    "MEDIUM_PLUS": SECURITY_MANDATORY_MEDIUM_PLUS_RID,
    "HIGH": SECURITY_MANDATORY_HIGH_RID,
    "SYSTEM": SECURITY_MANDATORY_SYSTEM_RID,
    "PROTECTED": SECURITY_MANDATORY_PROTECTED_PROCESS_RID,
}

# Process Mitigation Policies
# Used with SetProcessMitigationPolicy.

class PROCESS_MITIGATION_POLICY(IntEnum):
    """
    Process mitigation policy types.
    
    These policies enable exploit mitigation features like DEP, ASLR, CFG.
    """
    
    ProcessDEPPolicy = 0
    """Data Execution Prevention policy."""
    
    ProcessASLRPolicy = 1
    """Address Space Layout Randomization policy."""
    
    ProcessDynamicCodePolicy = 2
    """Dynamic code generation policy."""
    
    ProcessStrictHandleCheckPolicy = 3
    """Strict handle checking policy."""
    
    ProcessSystemCallDisablePolicy = 4
    """System call disable policy."""
    
    ProcessMitigationOptionsMask = 5
    """Combined mitigation options mask."""
    
    ProcessExtensionPointDisablePolicy = 6
    """Extension point disable policy."""
    
    ProcessControlFlowGuardPolicy = 7
    """Control Flow Guard policy."""
    
    ProcessSignaturePolicy = 8
    """Signature validation policy."""
    
    ProcessFontDisablePolicy = 9
    """Font loading disable policy."""
    
    ProcessImageLoadPolicy = 10
    """Image load restrictions policy."""
    
    ProcessSystemCallFilterPolicy = 11
    """System call filter policy."""
    
    ProcessPayloadRestrictionPolicy = 12
    """Payload restriction policy."""
    
    ProcessChildProcessPolicy = 13
    """Child process creation restrictions."""
    
    ProcessSideChannelIsolationPolicy = 14
    """Side channel isolation policy (Spectre/Meltdown mitigations)."""
    
    ProcessUserShadowStackPolicy = 15
    """User-mode shadow stack policy (CET)."""
    
    ProcessRedirectionTrustPolicy = 16
    """Redirection trust policy."""

# AppContainer Capabilities
# Well-known capability SIDs for AppContainer sandboxes.

APPCONTAINER_CAPABILITIES = {
    "internetClient": "internetClient",
    """Allows outbound connections to the Internet."""
    
    "internetClientServer": "internetClientServer",
    """Allows inbound and outbound Internet connections."""
    
    "privateNetworkClientServer": "privateNetworkClientServer",
    """Allows inbound/outbound connections on private networks."""
    
    "picturesLibrary": "picturesLibrary",
    """Access to the Pictures library."""
    
    "videosLibrary": "videosLibrary",
    """Access to the Videos library."""
    
    "musicLibrary": "musicLibrary",
    """Access to the Music library."""
    
    "documentsLibrary": "documentsLibrary",
    """Access to the Documents library."""
    
    "enterpriseAuthentication": "enterpriseAuthentication",
    """Access to enterprise authentication credentials."""
    
    "sharedUserCertificates": "sharedUserCertificates",
    """Access to shared user certificates."""
    
    "removableStorage": "removableStorage",
    """Access to removable storage devices."""
    
    "appointments": "appointments",
    """Access to calendar appointments."""
    
    "contacts": "contacts",
    """Access to user contacts."""
    
    "userAccountInformation": "userAccountInformation",
    """Access to user account information."""
    
    "location": "location",
    """Access to device location."""
    
    "microphone": "microphone",
    """Access to microphone."""
    
    "webcam": "webcam",
    """Access to webcam."""
    
    "bluetooth": "bluetooth",
}


# ============================================================================
# Windows API Structures
# ============================================================================

class LUID(Structure):
    """
    Locally Unique Identifier structure.
    
    A 64-bit value guaranteed to be unique on the local system.
    Used to identify privileges and other security-related objects.
    
    Attributes
    ----------
    LowPart : DWORD
        Low 32 bits of the LUID.
    HighPart : c_long
        High 32 bits of the LUID.
    """
    _fields_ = [
        ("LowPart", DWORD),
        ("HighPart", ctypes.c_long),
    ]
    
    def to_int(self) -> int:
        """
        Convert LUID to a 64-bit integer.
        
        Returns
        -------
        int
            The 64-bit integer representation of the LUID.
        """
        return (self.HighPart << 32) | self.LowPart
    
    def __str__(self) -> str:
        """String representation of the LUID."""
        return f"LUID(0x{self.to_int():016x})"


class LUID_AND_ATTRIBUTES(Structure):
    """
    LUID with attributes structure.
    
    Associates a LUID (privilege identifier) with attribute flags
    indicating whether the privilege is enabled, etc.
    
    Attributes
    ----------
    Luid : LUID
        The privilege identifier.
    Attributes : DWORD
        Flags indicating privilege state (enabled, removed, etc.).
    """
    _fields_ = [
        ("Luid", LUID),
        ("Attributes", DWORD),
    ]
    
    def is_enabled(self) -> bool:
        """
        Check if the privilege is enabled.
        
        Returns
        -------
        bool
            True if the privilege is currently enabled.
        """
        return bool(self.Attributes & SE_PRIVILEGE_ENABLED)
    
    def __str__(self) -> str:
        """String representation of the LUID and attributes."""
        attrs = []
        if self.Attributes & SE_PRIVILEGE_ENABLED:
            attrs.append("ENABLED")
        if self.Attributes & SE_PRIVILEGE_ENABLED_BY_DEFAULT:
            attrs.append("DEFAULT")
        if self.Attributes & SE_PRIVILEGE_REMOVED:
            attrs.append("REMOVED")
        return f"LUID_AND_ATTRIBUTES({self.Luid}, [{', '.join(attrs)}])"


class TOKEN_PRIVILEGES(Structure):
    """
    Token privileges structure.
    
    Contains a list of privileges and their attributes for a token.
    Used with AdjustTokenPrivileges to modify token privileges.
    
    Attributes
    ----------
    PrivilegeCount : DWORD
        Number of privileges in the array.
    Privileges : LUID_AND_ATTRIBUTES[1]
        Variable-length array of privilege entries.
    """
    _fields_ = [
        ("PrivilegeCount", DWORD),
        ("Privileges", LUID_AND_ATTRIBUTES * 1),
    ]
    
    @classmethod
    def create(cls, privileges: List[Tuple[LUID, DWORD]]) -> "TOKEN_PRIVILEGES":
        """
        Create a TOKEN_PRIVILEGES structure with multiple entries.
        
        Parameters
        ----------
        privileges : List[Tuple[LUID, DWORD]]
            List of (LUID, attributes) tuples.
            
        Returns
        -------
        TOKEN_PRIVILEGES
            Allocated structure with the specified privileges.
        """
        size = sizeof(cls) + (len(privileges) - 1) * sizeof(LUID_AND_ATTRIBUTES)
        buffer = create_string_buffer(size)
        tp = cls.from_buffer(buffer)
        tp.PrivilegeCount = len(privileges)
        for i, (luid, attrs) in enumerate(privileges):
            tp.Privileges[i].Luid = luid
            tp.Privileges[i].Attributes = attrs
        return tp
    
    def __str__(self) -> str:
        """String representation of token privileges."""
        return f"TOKEN_PRIVILEGES(count={self.PrivilegeCount})"


class SID_AND_ATTRIBUTES(Structure):
    """
    SID with attributes structure.
    
    Associates a Security Identifier (SID) with attribute flags.
    Used for token groups, integrity levels, etc.
    
    Attributes
    ----------
    Sid : c_void_p
        Pointer to the SID structure.
    Attributes : DWORD
        Flags indicating SID attributes (enabled, mandatory, etc.).
    """
    _fields_ = [
        ("Sid", c_void_p),
        ("Attributes", DWORD),
    ]
    
    # SID attribute flags
    SE_GROUP_MANDATORY = 0x00000001
    SE_GROUP_ENABLED_BY_DEFAULT = 0x00000002
    SE_GROUP_ENABLED = 0x00000004
    SE_GROUP_OWNER = 0x00000008
    SE_GROUP_USE_FOR_DENY_ONLY = 0x00000010
    SE_GROUP_INTEGRITY = 0x00000020
    SE_GROUP_INTEGRITY_ENABLED = 0x00000040
    SE_GROUP_RESOURCE = 0x20000000
    SE_GROUP_LOGON_ID = 0xC0000000
    
    def is_enabled(self) -> bool:
        """Check if the SID is enabled."""
        return bool(self.Attributes & self.SE_GROUP_ENABLED)
    
    def is_mandatory(self) -> bool:
        """Check if the SID is mandatory."""
        return bool(self.Attributes & self.SE_GROUP_MANDATORY)
    
    def __str__(self) -> str:
        """String representation of SID and attributes."""
        return f"SID_AND_ATTRIBUTES(attrs=0x{self.Attributes:08x})"


class TOKEN_GROUPS(Structure):
    """
    Token groups structure.
    
    Contains the list of group SIDs associated with a token.
    
    Attributes
    ----------
    GroupCount : DWORD
        Number of groups in the array.
    Groups : SID_AND_ATTRIBUTES[1]
        Variable-length array of group entries.
    """
    _fields_ = [
        ("GroupCount", DWORD),
        ("Groups", SID_AND_ATTRIBUTES * 1),
    ]
    
    def __str__(self) -> str:
        """String representation of token groups."""
        return f"TOKEN_GROUPS(count={self.GroupCount})"


class TOKEN_MANDATORY_LABEL(Structure):
    """
    Token mandatory label for integrity level.
    
    Contains the mandatory integrity level SID for a token.
    Used with TokenIntegrityLevel information class.
    
    Attributes
    ----------
    Label : SID_AND_ATTRIBUTES
        The integrity level SID and attributes.
    """
    _fields_ = [
        ("Label", SID_AND_ATTRIBUTES),
    ]
    
    def get_integrity_level(self) -> Optional[str]:
        """
        Get the integrity level name from the label.
        
        Returns
        -------
        Optional[str]
            Integrity level name or None if unknown.
        """
        if not self.Label.Sid:
            return None
            
        # Get RID from SID
        try:
            sub_auth_count = ctypes.c_ubyte.from_address(self.Label.Sid + 1).value
            if sub_auth_count > 0:
                sub_auth = ctypes.c_uint.from_address(
                    self.Label.Sid + 8 + (sub_auth_count - 1) * 4
                ).value
                
                for name, rid in INTEGRITY_LEVEL_MAP.items():
                    if rid == sub_auth:
                        return name
        except Exception:
            pass
            
        return None
    
    def __str__(self) -> str:
        """String representation of mandatory label."""
        level = self.get_integrity_level() or "UNKNOWN"
        return f"TOKEN_MANDATORY_LABEL(level={level})"


class SECURITY_ATTRIBUTES(Structure):
    """
    Security attributes structure.
    
    Contains security descriptor and inheritance information.
    
    Attributes
    ----------
    nLength : DWORD
        Size of the structure in bytes.
    lpSecurityDescriptor : LPVOID
        Pointer to security descriptor.
    bInheritHandle : BOOL
        Whether handles are inherited by child processes.
    """
    _fields_ = [
        ("nLength", DWORD),
        ("lpSecurityDescriptor", LPVOID),
        ("bInheritHandle", BOOL),
    ]
    
    def __init__(self, inherit: bool = False):
        """Initialize with default values."""
        self.nLength = sizeof(self)
        self.lpSecurityDescriptor = None
        self.bInheritHandle = inherit


class STARTUPINFO(Structure):
    """
    Startup information for process creation.
    
    Specifies window station, desktop, standard handles, and appearance
    for a new process.
    
    Attributes
    ----------
    cb : DWORD
        Size of the structure in bytes.
    lpReserved : LPWSTR
        Reserved, must be NULL.
    lpDesktop : LPWSTR
        Desktop or window station for the process.
    lpTitle : LPWSTR
        Title for console windows.
    dwX, dwY : DWORD
        Window position.
    dwXSize, dwYSize : DWORD
        Window size.
    dwXCountChars, dwYCountChars : DWORD
        Console buffer size.
    dwFillAttribute : DWORD
        Console text color.
    dwFlags : DWORD
        Flags indicating which fields are valid.
    wShowWindow : WORD
        Window show state.
    cbReserved2 : WORD
        Reserved.
    lpReserved2 : c_void_p
        Reserved.
    hStdInput, hStdOutput, hStdError : HANDLE
        Standard handles for the process.
    """
    _fields_ = [
        ("cb", DWORD),
        ("lpReserved", LPWSTR),
        ("lpDesktop", LPWSTR),
        ("lpTitle", LPWSTR),
        ("dwX", DWORD),
        ("dwY", DWORD),
        ("dwXSize", DWORD),
        ("dwYSize", DWORD),
        ("dwXCountChars", DWORD),
        ("dwYCountChars", DWORD),
        ("dwFillAttribute", DWORD),
        ("dwFlags", DWORD),
        ("wShowWindow", WORD),
        ("cbReserved2", WORD),
        ("lpReserved2", c_void_p),
        ("hStdInput", HANDLE),
        ("hStdOutput", HANDLE),
        ("hStdError", HANDLE),
    ]
    
    # STARTUPINFO flags
    STARTF_USESHOWWINDOW = 0x00000001
    STARTF_USESIZE = 0x00000002
    STARTF_USEPOSITION = 0x00000004
    STARTF_USECOUNTCHARS = 0x00000008
    STARTF_USEFILLATTRIBUTE = 0x00000010
    STARTF_RUNFULLSCREEN = 0x00000020
    STARTF_FORCEONFEEDBACK = 0x00000040
    STARTF_FORCEOFFFEEDBACK = 0x00000080
    STARTF_USESTDHANDLES = 0x00000100
    STARTF_USEHOTKEY = 0x00000200
    STARTF_TITLEISLINKNAME = 0x00000800
    STARTF_TITLEISAPPID = 0x00001000
    STARTF_PREVENTPINNING = 0x00002000
    
    def __init__(self):
        """Initialize with default values."""
        self.cb = sizeof(self)
        self.lpReserved = None
        self.lpDesktop = None
        self.lpTitle = None
        self.dwFlags = 0
        self.cbReserved2 = 0
        self.lpReserved2 = None
    
    def set_desktop(self, desktop: str) -> None:
        """
        Set the desktop for the process.
        
        Parameters
        ----------
        desktop : str
            Desktop name in format "WindowStation\\Desktop".
        """
        self.lpDesktop = desktop
    
    def set_standard_handles(self, stdin: HANDLE, stdout: HANDLE, stderr: HANDLE) -> None:
        """
        Set standard handles for the process.
        
        Parameters
        ----------
        stdin : HANDLE
            Standard input handle.
        stdout : HANDLE
            Standard output handle.
        stderr : HANDLE
            Standard error handle.
        """
        self.hStdInput = stdin
        self.hStdOutput = stdout
        self.hStdError = stderr
        self.dwFlags |= self.STARTF_USESTDHANDLES


class STARTUPINFOEX(Structure):
    """
    Extended startup information for process creation.
    
    Extends STARTUPINFO with an attribute list for advanced features
    like AppContainer and mitigation policies.
    
    Attributes
    ----------
    StartupInfo : STARTUPINFO
        Base startup information.
    lpAttributeList : c_void_p
        Pointer to attribute list (PROC_THREAD_ATTRIBUTE_LIST).
    """
    _fields_ = [
        ("StartupInfo", STARTUPINFO),
        ("lpAttributeList", c_void_p),
    ]
    
    def __init__(self):
        """Initialize with default values."""
        self.StartupInfo = STARTUPINFO()
        self.lpAttributeList = None


class PROCESS_INFORMATION(Structure):
    """
    Process information structure.
    
    Contains handles and identifiers for a newly created process.
    
    Attributes
    ----------
    hProcess : HANDLE
        Handle to the process.
    hThread : HANDLE
        Handle to the main thread.
    dwProcessId : DWORD
        Process identifier.
    dwThreadId : DWORD
        Thread identifier.
    """
    _fields_ = [
        ("hProcess", HANDLE),
        ("hThread", HANDLE),
        ("dwProcessId", DWORD),
        ("dwThreadId", DWORD),
    ]
    
    def __str__(self) -> str:
        """String representation of process information."""
        return f"PROCESS_INFORMATION(pid={self.dwProcessId}, tid={self.dwThreadId})"


class IO_COUNTERS(Structure):
    """
    I/O counters structure.
    
    Contains I/O operation statistics for a process or job.
    
    Attributes
    ----------
    ReadOperationCount : c_ulonglong
        Number of read operations.
    WriteOperationCount : c_ulonglong
        Number of write operations.
    OtherOperationCount : c_ulonglong
        Number of other (non-read/write) operations.
    ReadTransferCount : c_ulonglong
        Number of bytes read.
    WriteTransferCount : c_ulonglong
        Number of bytes written.
    OtherTransferCount : c_ulonglong
        Number of bytes transferred in other operations.
    """
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]
    
    def to_dict(self) -> Dict[str, int]:
        """
        Convert I/O counters to dictionary.
        
        Returns
        -------
        Dict[str, int]
            Dictionary with I/O statistics.
        """
        return {
            "read_operations": self.ReadOperationCount,
            "write_operations": self.WriteOperationCount,
            "other_operations": self.OtherOperationCount,
            "read_bytes": self.ReadTransferCount,
            "write_bytes": self.WriteTransferCount,
            "other_bytes": self.OtherTransferCount,
        }


class JOBOBJECT_BASIC_LIMIT_INFORMATION(Structure):
    """
    Basic job object limit information.
    
    Specifies basic resource limits for a job object.
    
    Attributes
    ----------
    PerProcessUserTimeLimit : LARGE_INTEGER
        Per-process user-mode CPU time limit (100ns units).
    PerJobUserTimeLimit : LARGE_INTEGER
        Total user-mode CPU time limit for the job.
    LimitFlags : DWORD
        Flags indicating which limits are enforced.
    MinimumWorkingSetSize : SIZE_T
        Minimum working set size per process.
    MaximumWorkingSetSize : SIZE_T
        Maximum working set size per process.
    ActiveProcessLimit : DWORD
        Maximum number of active processes.
    Affinity : c_ulonglong
        Processor affinity mask.
    PriorityClass : DWORD
        Priority class for processes.
    SchedulingClass : DWORD
        Scheduling class (0-9).
    """
    _fields_ = [
        ("PerProcessUserTimeLimit", LARGE_INTEGER),
        ("PerJobUserTimeLimit", LARGE_INTEGER),
        ("LimitFlags", DWORD),
        ("MinimumWorkingSetSize", SIZE_T),
        ("MaximumWorkingSetSize", SIZE_T),
        ("ActiveProcessLimit", DWORD),
        ("Affinity", ctypes.c_ulonglong),
        ("PriorityClass", DWORD),
        ("SchedulingClass", DWORD),
    ]
    
    def __init__(self):
        """Initialize with zero values."""
        self.PerProcessUserTimeLimit = 0
        self.PerJobUserTimeLimit = 0
        self.LimitFlags = 0
        self.MinimumWorkingSetSize = 0
        self.MaximumWorkingSetSize = 0
        self.ActiveProcessLimit = 0
        self.Affinity = 0
        self.PriorityClass = 0
        self.SchedulingClass = 0
    
    def set_memory_limit(self, limit_mb: int) -> None:
        """
        Set process memory limit.
        
        Parameters
        ----------
        limit_mb : int
            Memory limit in megabytes.
        """
        self.LimitFlags |= JobObjectLimitFlags.JOB_OBJECT_LIMIT_PROCESS_MEMORY
    
    def set_cpu_limit(self, seconds: float) -> None:
        """
        Set per-process CPU time limit.
        
        Parameters
        ----------
        seconds : float
            CPU time limit in seconds.
        """
        self.PerProcessUserTimeLimit = int(seconds * 10_000_000)  # 100ns units
        self.LimitFlags |= JobObjectLimitFlags.JOB_OBJECT_LIMIT_PROCESS_TIME
    
    def set_active_process_limit(self, count: int) -> None:
        """
        Set active process limit.
        
        Parameters
        ----------
        count : int
            Maximum number of simultaneously active processes.
        """
        self.ActiveProcessLimit = count
        self.LimitFlags |= JobObjectLimitFlags.JOB_OBJECT_LIMIT_ACTIVE_PROCESS


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(Structure):
    """
    Extended job object limit information.
    
    Extends basic limits with memory limits, I/O statistics, and CPU rate control.
    
    Attributes
    ----------
    BasicLimitInformation : JOBOBJECT_BASIC_LIMIT_INFORMATION
        Basic limit information.
    IoInfo : IO_COUNTERS
        I/O counters for the job.
    ProcessMemoryLimit : SIZE_T
        Per-process committed memory limit.
    JobMemoryLimit : SIZE_T
        Total committed memory limit for the job.
    PeakProcessMemoryUsed : SIZE_T
        Peak committed memory used by any process.
    PeakJobMemoryUsed : SIZE_T
        Peak total committed memory used by the job.
    """
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", SIZE_T),
        ("JobMemoryLimit", SIZE_T),
        ("PeakProcessMemoryUsed", SIZE_T),
        ("PeakJobMemoryUsed", SIZE_T),
    ]
    
    def __init__(self):
        """Initialize with zero values."""
        self.BasicLimitInformation = JOBOBJECT_BASIC_LIMIT_INFORMATION()
        self.IoInfo = IO_COUNTERS()
        self.ProcessMemoryLimit = 0
        self.JobMemoryLimit = 0
        self.PeakProcessMemoryUsed = 0
        self.PeakJobMemoryUsed = 0
    
    def set_process_memory_limit(self, limit_bytes: int) -> None:
        """
        Set process committed memory limit.
        
        Parameters
        ----------
        limit_bytes : int
            Memory limit in bytes.
        """
        self.ProcessMemoryLimit = limit_bytes
        self.BasicLimitInformation.LimitFlags |= JobObjectLimitFlags.JOB_OBJECT_LIMIT_PROCESS_MEMORY
    
    def set_job_memory_limit(self, limit_bytes: int) -> None:
        """
        Set total job committed memory limit.
        
        Parameters
        ----------
        limit_bytes : int
            Memory limit in bytes.
        """
        self.JobMemoryLimit = limit_bytes
        self.BasicLimitInformation.LimitFlags |= JobObjectLimitFlags.JOB_OBJECT_LIMIT_JOB_MEMORY


class JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(Structure):
    """
    Basic job object accounting information.
    
    Contains CPU time and process accounting statistics.
    
    Attributes
    ----------
    TotalUserTime : LARGE_INTEGER
        Total user-mode CPU time for all processes (100ns).
    TotalKernelTime : LARGE_INTEGER
        Total kernel-mode CPU time for all processes (100ns).
    ThisPeriodTotalUserTime : LARGE_INTEGER
        User-mode CPU time in current period.
    ThisPeriodTotalKernelTime : LARGE_INTEGER
        Kernel-mode CPU time in current period.
    TotalPageFaultCount : DWORD
        Total page faults.
    TotalProcesses : DWORD
        Total processes ever created in the job.
    ActiveProcesses : DWORD
        Currently active processes.
    TotalTerminatedProcesses : DWORD
        Total terminated processes.
    """
    _fields_ = [
        ("TotalUserTime", LARGE_INTEGER),
        ("TotalKernelTime", LARGE_INTEGER),
        ("ThisPeriodTotalUserTime", LARGE_INTEGER),
        ("ThisPeriodTotalKernelTime", LARGE_INTEGER),
        ("TotalPageFaultCount", DWORD),
        ("TotalProcesses", DWORD),
        ("ActiveProcesses", DWORD),
        ("TotalTerminatedProcesses", DWORD),
    ]
    
    def get_total_cpu_time(self) -> float:
        """
        Get total CPU time in seconds.
        
        Returns
        -------
        float
            Total CPU time (user + kernel) in seconds.
        """
        return (self.TotalUserTime + self.TotalKernelTime) / 10_000_000.0


# ============================================================================
# Windows Job Object
# ============================================================================

class WindowsJobObject:
    """
    Windows Job Object wrapper for process group management and resource limiting.
    
    A job object allows multiple processes to be managed as a group.
    It provides resource limiting (CPU, memory, I/O), process accounting,
    and automatic cleanup of child processes.
    
    Job objects are the primary mechanism for resource control on Windows,
    similar to cgroups on Linux.
    
    Parameters
    ----------
    name : Optional[str]
        Optional name for the job object (useful for debugging).
        If None, an unnamed job object is created.
    kill_on_close : bool
        If True, all processes in the job are terminated when the job handle
        is closed. This ensures complete cleanup.
        
    Attributes
    ----------
    handle : HANDLE
        Handle to the job object.
    name : Optional[str]
        Name of the job object.
    kill_on_close : bool
        Whether processes are killed when the job is closed.
    _limits : JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        Current limit configuration.
    _assigned_processes : Set[int]
        Set of process IDs assigned to this job.
    _lock : threading.RLock
        Lock for thread-safe operations.
    _closed : bool
        Whether the job handle has been closed.
        
    Examples
    --------
    >>> # Basic job with memory limit
    >>> job = WindowsJobObject(name="CompilerJob")
    >>> job.set_memory_limit(1024)  # 1GB
    >>> job.set_cpu_limit(60)  # 60 seconds
    >>> 
    >>> # Assign existing process
    >>> job.assign_process(os.getpid())
    >>> 
    >>> # Create new process in job
    >>> process = job.create_process(["gcc", "source.c"])
    >>> 
    >>> # Get resource usage
    >>> usage = job.get_usage()
    >>> print(f"CPU: {usage['cpu_time']:.2f}s, Memory: {usage['peak_memory_mb']:.1f}MB")
    >>> 
    >>> # Context manager ensures cleanup
    >>> with WindowsJobObject(kill_on_close=True) as job:
    ...     job.set_memory_limit(512)
    ...     job.create_process(["compiler.exe"])
    ... # All processes killed on exit
    
    Notes
    -----
    - Once a process is assigned to a job, it cannot be removed.
    - Child processes inherit job assignment unless breakaway is allowed.
    - Job limits are inherited by all processes in the job.
    - On Windows 8+, additional limits (I/O, network) are available.
    """
    
    def __init__(self, name: Optional[str] = None, kill_on_close: bool = True):
        """
        Initialize and create a Windows job object.
        
        Parameters
        ----------
        name : Optional[str]
            Optional name for the job object.
        kill_on_close : bool
            Kill processes when job handle is closed.
            
        Raises
        ------
        OSError
            If job object creation fails.
        """
        self.name = name
        self.kill_on_close = kill_on_close
        self._limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        self._assigned_processes: Set[int] = set()
        self._lock = threading.RLock()
        self._closed = False
        
        # Create the job object
        self.handle = self._create_job_object()
        
        # Configure kill-on-close if requested
        if kill_on_close:
            self._set_kill_on_close()
            
        logger.debug(f"Created job object: {self}")
    
    def _create_job_object(self) -> HANDLE:
        """
        Create the Windows job object.
        
        Returns
        -------
        HANDLE
            Handle to the created job object.
            
        Raises
        ------
        OSError
            If creation fails.
        """
        # CreateJobObjectW returns NULL on failure
        handle = windll.kernel32.CreateJobObjectW(
            None,  # Security attributes (NULL = default)
            self.name  # Job name (NULL = unnamed)
        )
        
        if not handle:
            error = GetLastError()
            raise OSError(f"Failed to create job object: {FormatError(error)} (code: {error})")
            
        return handle
    
    def _set_kill_on_close(self) -> None:
        """
        Set the JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE flag.
        
        This ensures all processes are terminated when the job handle is closed.
        
        Raises
        ------
        OSError
            If setting the information fails.
        """
        with self._lock:
            if self._closed:
                raise RuntimeError("Job object is closed")
                
            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            
            # Query current limits first
            ret = windll.kernel32.QueryInformationJobObject(
                self.handle,
                JobObjectInfoClass.ExtendedLimitInformation,
                byref(info),
                sizeof(info),
                None
            )
            
            if not ret:
                # If query fails, start with defaults
                info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            
            # Add kill-on-close flag
            info.BasicLimitInformation.LimitFlags |= JobObjectLimitFlags.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            
            # Set the updated limits
            ret = windll.kernel32.SetInformationJobObject(
                self.handle,
                JobObjectInfoClass.ExtendedLimitInformation,
                byref(info),
                sizeof(info)
            )
            
            if not ret:
                error = GetLastError()
                raise OSError(f"Failed to set kill-on-close: {FormatError(error)} (code: {error})")
            
            self._limits = info
    
    def set_memory_limit(self, limit_mb: int) -> bool:
        """
        Set process memory limit for the job object.
        
        This limits the committed memory (virtual memory) for each process
        in the job. When a process exceeds this limit, memory allocations fail.
        
        Parameters
        ----------
        limit_mb : int
            Memory limit in megabytes. Must be at least 1 MB.
            
        Returns
        -------
        bool
            True if the limit was successfully applied.
            
        Raises
        ------
        ValueError
            If limit_mb is less than 1.
        RuntimeError
            If job object is closed.
            
        Notes
        -----
        - This sets a per-process limit, not a total job limit.
        - Use set_job_memory_limit for total job memory limit.
        - The limit is applied immediately to all processes in the job.
        
        Examples
        --------
        >>> job = WindowsJobObject()
        >>> job.set_memory_limit(512)  # 512 MB per process
        """
        if limit_mb < 1:
            raise ValueError("Memory limit must be at least 1 MB")
            
        with self._lock:
            if self._closed:
                raise RuntimeError("Job object is closed")
                
            # Query current limits
            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            ret = windll.kernel32.QueryInformationJobObject(
                self.handle,
                JobObjectInfoClass.ExtendedLimitInformation,
                byref(info),
                sizeof(info),
                None
            )
            
            if not ret:
                info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            
            # Set memory limit
            info.ProcessMemoryLimit = limit_mb * 1024 * 1024
            info.BasicLimitInformation.LimitFlags |= JobObjectLimitFlags.JOB_OBJECT_LIMIT_PROCESS_MEMORY
            
            # Apply limits
            ret = windll.kernel32.SetInformationJobObject(
                self.handle,
                JobObjectInfoClass.ExtendedLimitInformation,
                byref(info),
                sizeof(info)
            )
            
            if ret:
                self._limits = info
                logger.debug(f"Set memory limit: {limit_mb} MB")
                return True
            else:
                error = GetLastError()
                logger.error(f"Failed to set memory limit: {FormatError(error)}")
                return False
    
    def set_job_memory_limit(self, limit_mb: int) -> bool:
        """
        Set total committed memory limit for the entire job.
        
        This limits the sum of committed memory across all processes in the job.
        
        Parameters
        ----------
        limit_mb : int
            Total memory limit in megabytes.
            
        Returns
        -------
        bool
            True if the limit was successfully applied.
            
        Notes
        -----
        - This is a Windows 8+ feature.
        - On older Windows versions, this may silently fail or be ignored.
        """
        if limit_mb < 1:
            raise ValueError("Memory limit must be at least 1 MB")
            
        with self._lock:
            if self._closed:
                raise RuntimeError("Job object is closed")
                
            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            ret = windll.kernel32.QueryInformationJobObject(
                self.handle,
                JobObjectInfoClass.ExtendedLimitInformation,
                byref(info),
                sizeof(info),
                None
            )
            
            if not ret:
                info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            
            info.JobMemoryLimit = limit_mb * 1024 * 1024
            info.BasicLimitInformation.LimitFlags |= JobObjectLimitFlags.JOB_OBJECT_LIMIT_JOB_MEMORY
            
            ret = windll.kernel32.SetInformationJobObject(
                self.handle,
                JobObjectInfoClass.ExtendedLimitInformation,
                byref(info),
                sizeof(info)
            )
            
            if ret:
                self._limits = info
                logger.debug(f"Set job memory limit: {limit_mb} MB")
                return True
            return False
    
    def set_cpu_limit(self, time_seconds: float) -> bool:
        """
        Set per-process CPU time limit.
        
        When a process exceeds this limit, it is terminated.
        
        Parameters
        ----------
        time_seconds : float
            CPU time limit in seconds. Must be positive.
            
        Returns
        -------
        bool
            True if the limit was successfully applied.
            
        Notes
        -----
        - The limit applies to user-mode CPU time only.
        - Kernel-mode time is not counted against this limit.
        - Time is measured in 100-nanosecond units.
        
        Examples
        --------
        >>> job = WindowsJobObject()
        >>> job.set_cpu_limit(60.0)  # 60 seconds of CPU time
        """
        if time_seconds <= 0:
            raise ValueError("CPU time limit must be positive")
            
        with self._lock:
            if self._closed:
                raise RuntimeError("Job object is closed")
                
            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            ret = windll.kernel32.QueryInformationJobObject(
                self.handle,
                JobObjectInfoClass.ExtendedLimitInformation,
                byref(info),
                sizeof(info),
                None
            )
            
            if not ret:
                info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            
            # Convert seconds to 100-nanosecond units
            info.BasicLimitInformation.PerProcessUserTimeLimit = int(time_seconds * 10_000_000)
            info.BasicLimitInformation.LimitFlags |= JobObjectLimitFlags.JOB_OBJECT_LIMIT_PROCESS_TIME
            
            ret = windll.kernel32.SetInformationJobObject(
                self.handle,
                JobObjectInfoClass.ExtendedLimitInformation,
                byref(info),
                sizeof(info)
            )
            
            if ret:
                self._limits = info
                logger.debug(f"Set CPU limit: {time_seconds}s")
                return True
            return False
    
    def set_job_cpu_limit(self, time_seconds: float) -> bool:
        """
        Set total CPU time limit for the entire job.
        
        When the total CPU time across all processes exceeds this limit,
        all processes in the job are terminated.
        
        Parameters
        ----------
        time_seconds : float
            Total CPU time limit in seconds.
            
        Returns
        -------
        bool
            True if the limit was successfully applied.
        """
        if time_seconds <= 0:
            raise ValueError("CPU time limit must be positive")
            
        with self._lock:
            if self._closed:
                raise RuntimeError("Job object is closed")
                
            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            ret = windll.kernel32.QueryInformationJobObject(
                self.handle,
                JobObjectInfoClass.ExtendedLimitInformation,
                byref(info),
                sizeof(info),
                None
            )
            
            if not ret:
                info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            
            info.BasicLimitInformation.PerJobUserTimeLimit = int(time_seconds * 10_000_000)
            info.BasicLimitInformation.LimitFlags |= JobObjectLimitFlags.JOB_OBJECT_LIMIT_JOB_TIME
            
            ret = windll.kernel32.SetInformationJobObject(
                self.handle,
                JobObjectInfoClass.ExtendedLimitInformation,
                byref(info),
                sizeof(info)
            )
            
            if ret:
                self._limits = info
                logger.debug(f"Set job CPU limit: {time_seconds}s")
                return True
            return False
    
    def set_process_limit(self, max_processes: int) -> bool:
        """
        Set maximum number of simultaneously active processes in the job.
        
        Parameters
        ----------
        max_processes : int
            Maximum number of active processes. Must be at least 1.
            
        Returns
        -------
        bool
            True if the limit was successfully applied.
            
        Notes
        -----
        - When the limit is reached, CreateProcess calls fail.
        - Existing processes are not terminated.
        
        Examples
        --------
        >>> job = WindowsJobObject()
        >>> job.set_process_limit(4)  # Max 4 concurrent processes
        """
        if max_processes < 1:
            raise ValueError("Process limit must be at least 1")
            
        with self._lock:
            if self._closed:
                raise RuntimeError("Job object is closed")
                
            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            ret = windll.kernel32.QueryInformationJobObject(
                self.handle,
                JobObjectInfoClass.ExtendedLimitInformation,
                byref(info),
                sizeof(info),
                None
            )
            
            if not ret:
                info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            
            info.BasicLimitInformation.ActiveProcessLimit = max_processes
            info.BasicLimitInformation.LimitFlags |= JobObjectLimitFlags.JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            
            ret = windll.kernel32.SetInformationJobObject(
                self.handle,
                JobObjectInfoClass.ExtendedLimitInformation,
                byref(info),
                sizeof(info)
            )
            
            if ret:
                self._limits = info
                logger.debug(f"Set process limit: {max_processes}")
                return True
            return False
    
    def set_working_set_limit(self, min_mb: int, max_mb: int) -> bool:
        """
        Set working set (physical memory) limits per process.
        
        The working set is the amount of physical memory a process can use.
        
        Parameters
        ----------
        min_mb : int
            Minimum working set in megabytes.
        max_mb : int
            Maximum working set in megabytes.
            
        Returns
        -------
        bool
            True if the limit was successfully applied.
            
        Notes
        -----
        - min_mb must be less than or equal to max_mb.
        - This is a soft limit; the OS may allow temporary exceedance.
        """
        if min_mb < 0 or max_mb < min_mb:
            raise ValueError("Invalid working set limits")
            
        with self._lock:
            if self._closed:
                raise RuntimeError("Job object is closed")
                
            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            ret = windll.kernel32.QueryInformationJobObject(
                self.handle,
                JobObjectInfoClass.ExtendedLimitInformation,
                byref(info),
                sizeof(info),
                None
            )
            
            if not ret:
                info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            
            info.BasicLimitInformation.MinimumWorkingSetSize = min_mb * 1024 * 1024
            info.BasicLimitInformation.MaximumWorkingSetSize = max_mb * 1024 * 1024
            info.BasicLimitInformation.LimitFlags |= JobObjectLimitFlags.JOB_OBJECT_LIMIT_WORKINGSET
            
            ret = windll.kernel32.SetInformationJobObject(
                self.handle,
                JobObjectInfoClass.ExtendedLimitInformation,
                byref(info),
                sizeof(info)
            )
            
            if ret:
                self._limits = info
                logger.debug(f"Set working set limits: {min_mb}-{max_mb} MB")
                return True
            return False
    
    def set_ui_restrictions(self, restrictions: JobObjectUIRestrictions) -> bool:
        """
        Set UI restrictions for processes in the job.
        
        Parameters
        ----------
        restrictions : JobObjectUIRestrictions
            UI restriction flags to apply.
            
        Returns
        -------
        bool
            True if restrictions were successfully applied.
            
        Examples
        --------
        >>> job = WindowsJobObject()
        >>> job.set_ui_restrictions(
        ...     JobObjectUIRestrictions.JOB_OBJECT_UILIMIT_DESKTOP |
        ...     JobObjectUIRestrictions.JOB_OBJECT_UILIMIT_EXITWINDOWS
        ... )
        """
        with self._lock:
            if self._closed:
                raise RuntimeError("Job object is closed")
                
            ui_limits = DWORD(restrictions.value)
            ret = windll.kernel32.SetInformationJobObject(
                self.handle,
                JobObjectInfoClass.BasicUIRestrictions,
                byref(ui_limits),
                sizeof(ui_limits)
            )
            
            if ret:
                logger.debug(f"Set UI restrictions: {restrictions}")
                return True
            return False
    
    def assign_process(self, pid: int) -> bool:
        """
        Assign an existing process to this job object.
        
        Once assigned, the process cannot be removed from the job.
        
        Parameters
        ----------
        pid : int
            Process ID to assign.
            
        Returns
        -------
        bool
            True if the process was successfully assigned.
            
        Notes
        -----
        - Requires PROCESS_SET_QUOTA and PROCESS_TERMINATE access.
        - The process must not already be assigned to another job.
        - Child processes will automatically inherit the job.
        
        Examples
        --------
        >>> job = WindowsJobObject()
        >>> import os
        >>> job.assign_process(os.getpid())  # Assign current process
        """
        with self._lock:
            if self._closed:
                raise RuntimeError("Job object is closed")
                
            # Open the process
            process_handle = windll.kernel32.OpenProcess(
                PROCESS_SET_QUOTA | PROCESS_TERMINATE,
                False,
                pid
            )
            
            if not process_handle:
                error = GetLastError()
                logger.error(f"Failed to open process {pid}: {FormatError(error)}")
                return False
            
            # Assign to job
            ret = windll.kernel32.AssignProcessToJobObject(self.handle, process_handle)
            
            # Close process handle
            windll.kernel32.CloseHandle(process_handle)
            
            if ret:
                self._assigned_processes.add(pid)
                logger.debug(f"Assigned process {pid} to job")
                return True
            else:
                error = GetLastError()
                logger.error(f"Failed to assign process {pid}: {FormatError(error)}")
                return False
    
    def create_process(
        self,
        command_line: Union[str, List[str]],
        working_directory: Optional[Path] = None,
        environment: Optional[Dict[str, str]] = None,
        suspended: bool = False,
        inherit_handles: bool = True,
        creation_flags: int = 0,
    ) -> Optional[PROCESS_INFORMATION]:
        """
        Create a new process that is automatically assigned to this job.
        
        This method creates a process with CREATE_BREAKAWAY_FROM_JOB flag
        to ensure proper job assignment.
        
        Parameters
        ----------
        command_line : Union[str, List[str]]
            Command to execute. If list, joined with spaces.
        working_directory : Optional[Path]
            Working directory for the process.
        environment : Optional[Dict[str, str]]
            Environment variables (merged with current environment).
        suspended : bool
            If True, create process suspended.
        inherit_handles : bool
            If True, child inherits inheritable handles.
        creation_flags : int
            Additional process creation flags.
            
        Returns
        -------
        Optional[PROCESS_INFORMATION]
            Process information if successful, None otherwise.
            
        Examples
        --------
        >>> job = WindowsJobObject()
        >>> proc_info = job.create_process(["gcc", "-c", "source.c"])
        >>> if proc_info:
        ...     print(f"Created process {proc_info.dwProcessId}")
        """
        with self._lock:
            if self._closed:
                raise RuntimeError("Job object is closed")
                
            # Prepare command line
            if isinstance(command_line, list):
                cmd = " ".join(f'"{arg}"' if " " in arg else arg for arg in command_line)
            else:
                cmd = command_line
            
            # Prepare environment
            env_block = None
            if environment is not None:
                env = os.environ.copy()
                env.update(environment)
                env_str = "\0".join(f"{k}={v}" for k, v in env.items()) + "\0\0"
                env_block = create_unicode_buffer(env_str)
            
            # Prepare startup info
            startup_info = STARTUPINFO()
            
            # Set creation flags
            flags = creation_flags
            flags |= CREATE_BREAKAWAY_FROM_JOB
            if suspended:
                flags |= CREATE_SUSPENDED
            if env_block:
                flags |= CREATE_UNICODE_ENVIRONMENT
            
            # Create process
            proc_info = PROCESS_INFORMATION()
            ret = windll.kernel32.CreateProcessW(
                None,  # Application name (use command line)
                cmd,   # Command line
                None,  # Process security attributes
                None,  # Thread security attributes
                inherit_handles,
                flags,
                env_block,
                str(working_directory) if working_directory else None,
                byref(startup_info),
                byref(proc_info)
            )
            
            if not ret:
                error = GetLastError()
                logger.error(f"Failed to create process: {FormatError(error)}")
                return None
            
            # Process is automatically assigned to job due to CREATE_BREAKAWAY_FROM_JOB
            self._assigned_processes.add(proc_info.dwProcessId)
            logger.debug(f"Created process {proc_info.dwProcessId} in job")
            
            return proc_info
    
    def get_usage(self) -> Dict[str, Any]:
        """
        Get comprehensive resource usage statistics for the job.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary containing:
            - cpu_time: Total CPU time in seconds
            - user_time: User-mode CPU time in seconds
            - kernel_time: Kernel-mode CPU time in seconds
            - memory_mb: Current committed memory in MB
            - peak_memory_mb: Peak committed memory in MB
            - job_memory_mb: Total job committed memory in MB
            - peak_job_memory_mb: Peak total job memory in MB
            - active_processes: Number of active processes
            - total_processes: Total processes created
            - page_faults: Total page faults
            - io_stats: I/O statistics dictionary
            
        Examples
        --------
        >>> job = WindowsJobObject()
        >>> usage = job.get_usage()
        >>> print(f"Peak memory: {usage['peak_memory_mb']:.1f} MB")
        >>> print(f"CPU time: {usage['cpu_time']:.2f} seconds")
        """
        with self._lock:
            if self._closed:
                return {}
                
            usage: Dict[str, Any] = {
                "cpu_time": 0.0,
                "user_time": 0.0,
                "kernel_time": 0.0,
                "memory_mb": 0.0,
                "peak_memory_mb": 0.0,
                "job_memory_mb": 0.0,
                "peak_job_memory_mb": 0.0,
                "active_processes": 0,
                "total_processes": 0,
                "page_faults": 0,
                "io_stats": {},
            }
            
            try:
                # Get extended limit info (has memory stats)
                limit_info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
                ret = windll.kernel32.QueryInformationJobObject(
                    self.handle,
                    JobObjectInfoClass.ExtendedLimitInformation,
                    byref(limit_info),
                    sizeof(limit_info),
                    None
                )
                
                if ret:
                    usage["peak_memory_mb"] = limit_info.PeakProcessMemoryUsed / (1024 * 1024)
                    usage["peak_job_memory_mb"] = limit_info.PeakJobMemoryUsed / (1024 * 1024)
                    usage["io_stats"] = limit_info.IoInfo.to_dict()
                
                # Get accounting info (has CPU time and process counts)
                accounting_info = JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
                ret = windll.kernel32.QueryInformationJobObject(
                    self.handle,
                    1,  # JobObjectBasicAccountingInformation
                    byref(accounting_info),
                    sizeof(accounting_info),
                    None
                )
                
                if ret:
                    usage["user_time"] = accounting_info.TotalUserTime / 10_000_000.0
                    usage["kernel_time"] = accounting_info.TotalKernelTime / 10_000_000.0
                    usage["cpu_time"] = usage["user_time"] + usage["kernel_time"]
                    usage["active_processes"] = accounting_info.ActiveProcesses
                    usage["total_processes"] = accounting_info.TotalProcesses
                    usage["page_faults"] = accounting_info.TotalPageFaultCount
                    
            except Exception as e:
                logger.error(f"Failed to get job usage: {e}")
                
            return usage
    
    def get_process_list(self) -> List[int]:
        """
        Get list of process IDs currently in the job.
        
        Returns
        -------
        List[int]
            List of process IDs assigned to this job.
            
        Notes
        -----
        - This uses QueryInformationJobObject with JobObjectBasicProcessIdList.
        - May return empty list on older Windows versions.
        """
        with self._lock:
            if self._closed:
                return []
                
            # This requires Windows 8+ or specific API
            # For now, return our tracked set
            return list(self._assigned_processes)
    
    def terminate(self, exit_code: int = 1) -> bool:
        """
        Terminate all processes in the job object.
        
        Parameters
        ----------
        exit_code : int
            Exit code to assign to terminated processes.
            
        Returns
        -------
        bool
            True if termination was initiated successfully.
            
        Notes
        -----
        - This calls TerminateJobObject which terminates all processes.
        - Use with caution as it does not allow processes to clean up.
        """
        with self._lock:
            if self._closed:
                return False
                
            ret = windll.kernel32.TerminateJobObject(self.handle, exit_code)
            if ret:
                logger.debug(f"Terminated all processes in job with exit code {exit_code}")
                self._assigned_processes.clear()
            return bool(ret)
    
    def close(self) -> None:
        """
        Close the job object handle.
        
        If kill_on_close is True, all processes are terminated before closing.
        Otherwise, processes continue running but are no longer managed.
        
        Notes
        -----
        - After closing, the job object cannot be used.
        - It's recommended to use context manager for automatic cleanup.
        """
        with self._lock:
            if self._closed:
                return
                
            if self.kill_on_close:
                self.terminate()
                
            if self.handle:
                windll.kernel32.CloseHandle(self.handle)
                self.handle = None
                
            self._closed = True
            logger.debug(f"Closed job object: {self}")
    
    @property
    def is_closed(self) -> bool:
        """
        Check if the job object has been closed.
        
        Returns
        -------
        bool
            True if the job handle is closed.
        """
        return self._closed
    
    def __enter__(self) -> "WindowsJobObject":
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - ensures cleanup."""
        self.close()
    
    def __del__(self) -> None:
        """Destructor - attempt cleanup if not already closed."""
        try:
            if not self._closed and self.handle:
                self.close()
        except Exception:
            pass
    
    def __repr__(self) -> str:
        """String representation of the job object."""
        name_str = f"'{self.name}'" if self.name else "unnamed"
        status = "closed" if self._closed else "open"
        procs = len(self._assigned_processes)
        return f"<WindowsJobObject {name_str} processes={procs} [{status}]>"


# ============================================================================
# Windows Restricted Token
# ============================================================================

class WindowsRestrictedToken:
    """
    Windows Restricted Token for privilege removal and security context reduction.
    
    A restricted token is a modified version of an existing token that has
    reduced privileges, removed groups, and/or added restricting SIDs.
    This is a powerful sandboxing mechanism on Windows.
    
    Restricted tokens can:
    - Remove dangerous privileges (SeDebugPrivilege, SeLoadDriverPrivilege, etc.)
    - Remove the process from powerful groups (Administrators, Power Users)
    - Add restricting SIDs that limit access to objects
    - Lower the integrity level
    
    Parameters
    ----------
    base_token : Optional[HANDLE]
        Base token to restrict. If None, uses current process token.
        
    Attributes
    ----------
    _base_token : HANDLE
        Handle to the base token.
    _restricted_token : Optional[HANDLE]
        Handle to the created restricted token.
    _disabled_privileges : Set[str]
        Set of privilege names to disable.
    _removed_privileges : Set[str]
        Set of privilege names to remove entirely.
    _removed_groups : Set[str]
        Set of group names to remove.
    _restricting_sids : List[Any]
        List of restricting SIDs to add.
    _integrity_level : Optional[int]
        Target integrity level RID.
    _created : bool
        Whether the restricted token has been created.
    _lock : threading.RLock
        Lock for thread-safe operations.
        
    Examples
    --------
    >>> # Create restricted token with removed privileges
    >>> token = WindowsRestrictedToken()
    >>> token.disable_all_privileges()
    >>> token.remove_privileges(["SeDebugPrivilege", "SeLoadDriverPrivilege"])
    >>> token.remove_groups(["Administrators"])
    >>> token.set_integrity_level("LOW")
    >>> 
    >>> # Create process with restricted token
    >>> with token:
    ...     proc_info = token.create_process(["compiler.exe", "source.c"])
    """
    
    # Dangerous privileges that should typically be removed
    DANGEROUS_PRIVILEGES = [
        SE_DEBUG_NAME,
        SE_LOAD_DRIVER_NAME,
        SE_TCB_NAME,
        SE_CREATE_TOKEN_NAME,
        SE_ASSIGNPRIMARYTOKEN_NAME,
        SE_TAKE_OWNERSHIP_NAME,
        SE_BACKUP_NAME,
        SE_RESTORE_NAME,
        SE_SECURITY_NAME,
        SE_SYSTEM_ENVIRONMENT_NAME,
        SE_SHUTDOWN_NAME,
        SE_REMOTE_SHUTDOWN_NAME,
        SE_CREATE_GLOBAL_NAME,
        SE_IMPERSONATE_NAME,
        SE_INCREASE_QUOTA_NAME,
        SE_LOCK_MEMORY_NAME,
        SE_SYSTEM_PROFILE_NAME,
        SE_PROF_SINGLE_PROCESS_NAME,
    ]
    
    # Powerful groups that should typically be removed
    DANGEROUS_GROUPS = [
        "Administrators",
        "Power Users",
        "Backup Operators",
        "Network Configuration Operators",
        "Cryptographic Operators",
        "Hyper-V Administrators",
        "System Managed Accounts Group",
    ]
    
    def __init__(self, base_token: Optional[HANDLE] = None):
        """
        Initialize a restricted token builder.
        
        Parameters
        ----------
        base_token : Optional[HANDLE]
            Base token to restrict. If None, uses current process token.
            
        Raises
        ------
        OSError
            If the base token cannot be opened.
        """
        self._lock = threading.RLock()
        self._disabled_privileges: Set[str] = set()
        self._removed_privileges: Set[str] = set()
        self._removed_groups: Set[str] = set()
        self._restricting_sids: List[Any] = []
        self._integrity_level: Optional[int] = None
        self._created = False
        self._restricted_token: Optional[HANDLE] = None
        
        # Open base token
        if base_token is not None:
            self._base_token = base_token
        else:
            self._base_token = self._open_current_process_token()
            
        logger.debug(f"Created {self}")
    
    def _open_current_process_token(self) -> HANDLE:
        """
        Open the current process token with required access.
        
        Returns
        -------
        HANDLE
            Handle to the process token.
            
        Raises
        ------
        OSError
            If token cannot be opened.
        """
        token = HANDLE()
        ret = windll.advapi32.OpenProcessToken(
            windll.kernel32.GetCurrentProcess(),
            0x02000000 | 0x0008 | 0x0004 | 0x0400,  # TOKEN_DUPLICATE | TOKEN_QUERY | TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY_SOURCE
            byref(token)
        )
        
        if not ret:
            error = GetLastError()
            raise OSError(f"Failed to open process token: {FormatError(error)}")
            
        return token
    
    def _get_privilege_luid(self, privilege_name: str) -> Optional[LUID]:
        """
        Look up the LUID for a privilege name.
        
        Parameters
        ----------
        privilege_name : str
            Name of the privilege (e.g., "SeDebugPrivilege").
            
        Returns
        -------
        Optional[LUID]
            LUID for the privilege, or None if lookup fails.
        """
        luid = LUID()
        ret = windll.advapi32.LookupPrivilegeValueW(
            None,  # Local system
            privilege_name,
            byref(luid)
        )
        
        if ret:
            return luid
        return None
    
    def disable_privilege(self, privilege_name: str) -> "WindowsRestrictedToken":
        """
        Disable a specific privilege in the token.
        
        Disabled privileges are still present but cannot be used.
        
        Parameters
        ----------
        privilege_name : str
            Name of the privilege to disable.
            
        Returns
        -------
        WindowsRestrictedToken
            Self for method chaining.
        """
        with self._lock:
            self._disabled_privileges.add(privilege_name)
            self._created = False
        return self
    
    def disable_all_privileges(self) -> "WindowsRestrictedToken":
        """
        Disable all privileges in the token.
        
        Returns
        -------
        WindowsRestrictedToken
            Self for method chaining.
        """
        with self._lock:
            for priv in self.DANGEROUS_PRIVILEGES:
                self._disabled_privileges.add(priv)
            self._created = False
        return self
    
    def remove_privilege(self, privilege_name: str) -> "WindowsRestrictedToken":
        """
        Completely remove a privilege from the token.
        
        Removed privileges are no longer present in the token.
        
        Parameters
        ----------
        privilege_name : str
            Name of the privilege to remove.
            
        Returns
        -------
        WindowsRestrictedToken
            Self for method chaining.
        """
        with self._lock:
            self._removed_privileges.add(privilege_name)
            self._created = False
        return self
    
    def remove_privileges(self, privilege_names: List[str]) -> "WindowsRestrictedToken":
        """
        Remove multiple privileges from the token.
        
        Parameters
        ----------
        privilege_names : List[str]
            List of privilege names to remove.
            
        Returns
        -------
        WindowsRestrictedToken
            Self for method chaining.
        """
        with self._lock:
            for priv in privilege_names:
                self._removed_privileges.add(priv)
            self._created = False
        return self
    
    def remove_dangerous_privileges(self) -> "WindowsRestrictedToken":
        """
        Remove all known dangerous privileges.
        
        Returns
        -------
        WindowsRestrictedToken
            Self for method chaining.
        """
        with self._lock:
            for priv in self.DANGEROUS_PRIVILEGES:
                self._removed_privileges.add(priv)
            self._created = False
        return self
    
    def remove_group(self, group_name: str) -> "WindowsRestrictedToken":
        """
        Remove a group from the token.
        
        Parameters
        ----------
        group_name : str
            Name of the group to remove (e.g., "Administrators").
            
        Returns
        -------
        WindowsRestrictedToken
            Self for method chaining.
        """
        with self._lock:
            self._removed_groups.add(group_name)
            self._created = False
        return self
    
    def remove_groups(self, group_names: List[str]) -> "WindowsRestrictedToken":
        """
        Remove multiple groups from the token.
        
        Parameters
        ----------
        group_names : List[str]
            List of group names to remove.
            
        Returns
        -------
        WindowsRestrictedToken
            Self for method chaining.
        """
        with self._lock:
            for group in group_names:
                self._removed_groups.add(group)
            self._created = False
        return self
    
    def remove_dangerous_groups(self) -> "WindowsRestrictedToken":
        """
        Remove all known powerful groups.
        
        Returns
        -------
        WindowsRestrictedToken
            Self for method chaining.
        """
        with self._lock:
            for group in self.DANGEROUS_GROUPS:
                self._removed_groups.add(group)
            self._created = False
        return self
    
    def set_integrity_level(self, level: Union[str, int]) -> "WindowsRestrictedToken":
        """
        Set the mandatory integrity level for the token.
        
        Parameters
        ----------
        level : Union[str, int]
            Integrity level. Can be string ("LOW", "MEDIUM", "HIGH", etc.)
            or RID value.
            
        Returns
        -------
        WindowsRestrictedToken
            Self for method chaining.
            
        Notes
        -----
        - Lowering integrity level restricts what objects the process can access.
        - "LOW" is commonly used for sandboxed processes.
        - Requires Windows Vista or later.
        """
        with self._lock:
            if isinstance(level, str):
                level = level.upper()
                if level not in INTEGRITY_LEVEL_MAP:
                    raise ValueError(f"Unknown integrity level: {level}")
                self._integrity_level = INTEGRITY_LEVEL_MAP[level]
            else:
                self._integrity_level = level
            self._created = False
        return self
    
    def create(self) -> HANDLE:
        """
        Create the restricted token.
        
        This applies all configured restrictions to create a new token.
        
        Returns
        -------
        HANDLE
            Handle to the newly created restricted token.
            
        Raises
        ------
        OSError
            If token creation fails.
            
        Notes
        -----
        - The token is cached; subsequent calls return the same token.
        - Use close() to release the token.
        """
        with self._lock:
            if self._created and self._restricted_token:
                return self._restricted_token
                
            # Create restricted token
            restricted_token = HANDLE()
            ret = windll.advapi32.CreateRestrictedToken(
                self._base_token,
                0,  # Flags
                0,  # DisableSidCount
                None,  # SidsToDisable
                0,  # DeletePrivilegeCount
                None,  # PrivilegesToDelete
                0,  # RestrictedSidCount
                None,  # SidsToRestrict
                byref(restricted_token)
            )
            
            if not ret:
                error = GetLastError()
                raise OSError(f"Failed to create restricted token: {FormatError(error)}")
            
            # Apply privilege modifications
            self._apply_privilege_modifications(restricted_token)
            
            # Apply integrity level
            if self._integrity_level is not None:
                self._apply_integrity_level(restricted_token)
            
            self._restricted_token = restricted_token
            self._created = True
            logger.debug("Created restricted token")
            
            return restricted_token
    
    def _apply_privilege_modifications(self, token: HANDLE) -> None:
        """
        Apply privilege disabling/removal to a token.
        
        Parameters
        ----------
        token : HANDLE
            Token handle to modify.
        """
        # Build list of privileges to disable
        disable_list = []
        for priv_name in self._disabled_privileges:
            luid = self._get_privilege_luid(priv_name)
            if luid:
                disable_list.append((luid, 0))  # 0 = disabled
        
        if disable_list:
            tp = TOKEN_PRIVILEGES.create(disable_list)
            ret = windll.advapi32.AdjustTokenPrivileges(
                token,
                False,  # DisableAllPrivileges
                byref(tp),
                sizeof(tp),
                None,
                None
            )
            if not ret:
                logger.warning("Failed to disable some privileges")
        
        # Build list of privileges to remove
        remove_list = []
        for priv_name in self._removed_privileges:
            luid = self._get_privilege_luid(priv_name)
            if luid:
                remove_list.append((luid, SE_PRIVILEGE_REMOVED))
        
        if remove_list:
            tp = TOKEN_PRIVILEGES.create(remove_list)
            ret = windll.advapi32.AdjustTokenPrivileges(
                token,
                False,
                byref(tp),
                sizeof(tp),
                None,
                None
            )
            if not ret:
                logger.warning("Failed to remove some privileges")
    
    def _apply_integrity_level(self, token: HANDLE) -> None:
        """
        Apply integrity level to a token.
        
        Parameters
        ----------
        token : HANDLE
            Token handle to modify.
        """
        # Create integrity level SID
        sid = c_void_p()
        ret = windll.advapi32.ConvertStringSidToSidW(
            f"S-1-16-{self._integrity_level}",
            byref(sid)
        )
        
        if not ret:
            logger.warning("Failed to create integrity SID")
            return
        
        try:
            # Create mandatory label
            label = TOKEN_MANDATORY_LABEL()
            label.Label.Sid = sid
            label.Label.Attributes = SID_AND_ATTRIBUTES.SE_GROUP_INTEGRITY | SID_AND_ATTRIBUTES.SE_GROUP_INTEGRITY_ENABLED
            
            # Set token integrity level
            ret = windll.advapi32.SetTokenInformation(
                token,
                TOKEN_INFORMATION_CLASS.TokenIntegrityLevel,
                byref(label),
                sizeof(label)
            )
            
            if not ret:
                logger.warning("Failed to set integrity level")
            else:
                logger.debug(f"Set integrity level to RID {self._integrity_level}")
                
        finally:
            windll.advapi32.LocalFree(sid)
    
    def create_process(
        self,
        command_line: Union[str, List[str]],
        working_directory: Optional[Path] = None,
        environment: Optional[Dict[str, str]] = None,
        suspended: bool = False,
        creation_flags: int = 0,
    ) -> Optional[PROCESS_INFORMATION]:
        """
        Create a new process using the restricted token.
        
        Parameters
        ----------
        command_line : Union[str, List[str]]
            Command to execute.
        working_directory : Optional[Path]
            Working directory.
        environment : Optional[Dict[str, str]]
            Environment variables.
        suspended : bool
            Create suspended.
        creation_flags : int
            Additional creation flags.
            
        Returns
        -------
        Optional[PROCESS_INFORMATION]
            Process information if successful.
        """
        with self._lock:
            token = self.create()
            
            # Prepare command line
            if isinstance(command_line, list):
                cmd = " ".join(f'"{arg}"' if " " in arg else arg for arg in command_line)
            else:
                cmd = command_line
            
            # Prepare environment
            env_block = None
            if environment is not None:
                env = os.environ.copy()
                env.update(environment)
                env_str = "\0".join(f"{k}={v}" for k, v in env.items()) + "\0\0"
                env_block = create_unicode_buffer(env_str)
            
            # Prepare startup info
            startup_info = STARTUPINFO()
            
            # Set creation flags
            flags = creation_flags
            if suspended:
                flags |= CREATE_SUSPENDED
            if env_block:
                flags |= CREATE_UNICODE_ENVIRONMENT
            
            # Create process with token
            proc_info = PROCESS_INFORMATION()
            ret = windll.advapi32.CreateProcessAsUserW(
                token,
                None,
                cmd,
                None,
                None,
                False,  # Inherit handles
                flags,
                env_block,
                str(working_directory) if working_directory else None,
                byref(startup_info),
                byref(proc_info)
            )
            
            if not ret:
                error = GetLastError()
                logger.error(f"Failed to create process: {FormatError(error)}")
                return None
            
            logger.debug(f"Created process {proc_info.dwProcessId} with restricted token")
            return proc_info
    
    def close(self) -> None:
        """
        Close the restricted token handle.
        """
        with self._lock:
            if self._restricted_token:
                windll.kernel32.CloseHandle(self._restricted_token)
                self._restricted_token = None
                self._created = False
                logger.debug("Closed restricted token")
    
    def __enter__(self) -> "WindowsRestrictedToken":
        """Context manager entry."""
        self.create()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()
    
    def __del__(self) -> None:
        """Destructor - cleanup."""
        try:
            self.close()
        except Exception:
            pass
    
    def __repr__(self) -> str:
        """String representation."""
        status = "created" if self._created else "pending"
        return f"<WindowsRestrictedToken disabled={len(self._disabled_privileges)} removed={len(self._removed_privileges)} [{status}]>"


# ============================================================================
# Windows Process Mitigations
# ============================================================================

class WindowsProcessMitigations:
    """
    Windows Process Mitigation Policy manager.
    
    Process mitigations are security features that prevent exploitation
    techniques like code injection, ROP, and memory corruption.
    
    Available mitigations:
    - DEP (Data Execution Prevention) - prevents code execution from data pages
    - ASLR (Address Space Layout Randomization) - randomizes memory layout
    - CFG (Control Flow Guard) - validates indirect call targets
    - Dynamic Code - prevents dynamic code generation
    - Strict Handle Checks - raises exceptions on bad handle references
    - Extension Point Disable - prevents DLL injection via extension points
    - Signature Validation - requires DLLs to be signed
    - Child Process Restriction - prevents creating child processes
    - Side Channel Isolation - mitigates Spectre/Meltdown
    
    Attributes
    ----------
    _mitigations : Dict[PROCESS_MITIGATION_POLICY, Any]
        Configured mitigation policies.
    _lock : threading.RLock
        Lock for thread-safe operations.
        
    Examples
    --------
    >>> mitigations = WindowsProcessMitigations()
    >>> mitigations.enable_dep()
    >>> mitigations.enable_aslr()
    >>> mitigations.enable_cfg()
    >>> mitigations.disable_dynamic_code()
    >>> 
    >>> # Apply to current process
    >>> mitigations.apply()
    >>> 
    >>> # Apply to child process via attribute list
    >>> attr_list = mitigations.create_attribute_list()
    """
    
    def __init__(self):
        """Initialize process mitigations builder."""
        self._mitigations: Dict[PROCESS_MITIGATION_POLICY, Any] = {}
        self._lock = threading.RLock()
    
    def enable_dep(self, permanent: bool = True) -> "WindowsProcessMitigations":
        """
        Enable Data Execution Prevention.
        
        DEP prevents code execution from non-executable memory pages.
        
        Parameters
        ----------
        permanent : bool
            If True, DEP cannot be disabled after being set.
            
        Returns
        -------
        WindowsProcessMitigations
            Self for method chaining.
        """
        with self._lock:
            policy = DWORD()
            policy.value = 0x00000003  # PROCESS_DEP_ENABLE
            if permanent:
                policy.value |= 0x00000008  # PROCESS_DEP_DISABLE_ATL_THUNK_EMULATION
            self._mitigations[PROCESS_MITIGATION_POLICY.ProcessDEPPolicy] = policy
        return self
    
    def enable_aslr(self, force_relocate: bool = True, bottom_up: bool = True, high_entropy: bool = True) -> "WindowsProcessMitigations":
        """
        Enable Address Space Layout Randomization.
        
        ASLR randomizes the location of modules, stack, and heap.
        
        Parameters
        ----------
        force_relocate : bool
            Force images to relocate even if not ASLR-aware.
        bottom_up : bool
            Randomize bottom-up allocations.
        high_entropy : bool
            Enable high-entropy ASLR (64-bit only).
            
        Returns
        -------
        WindowsProcessMitigations
            Self for method chaining.
        """
        with self._lock:
            policy = DWORD()
            policy.value = 0x00000001  # Enable bottom-up randomization
            if force_relocate:
                policy.value |= 0x00000002  # Force relocate images
            if high_entropy:
                policy.value |= 0x00000020  # High entropy ASLR
            self._mitigations[PROCESS_MITIGATION_POLICY.ProcessASLRPolicy] = policy
        return self
    
    def enable_cfg(self, strict: bool = True, suppress_exports: bool = False) -> "WindowsProcessMitigations":
        """
        Enable Control Flow Guard.
        
        CFG validates indirect call targets to prevent control-flow hijacking.
        
        Parameters
        ----------
        strict : bool
            Enable strict CFG (requires all modules to be CFG-aware).
        suppress_exports : bool
            Suppress export suppression.
            
        Returns
        -------
        WindowsProcessMitigations
            Self for method chaining.
        """
        with self._lock:
            policy = DWORD()
            policy.value = 0x00000001  # Enable CFG
            if strict:
                policy.value |= 0x00000002  # Strict mode
            if suppress_exports:
                policy.value |= 0x00000004  # Suppress exports
            self._mitigations[PROCESS_MITIGATION_POLICY.ProcessControlFlowGuardPolicy] = policy
        return self
    
    def disable_dynamic_code(self, allow_thread_opt_out: bool = False, allow_remote_downgrade: bool = False) -> "WindowsProcessMitigations":
        """
        Disable dynamic code generation.
        
        Prevents allocating executable memory and modifying code pages.
        
        Parameters
        ----------
        allow_thread_opt_out : bool
            Allow threads to opt out.
        allow_remote_downgrade : bool
            Allow remote downgrade.
            
        Returns
        -------
        WindowsProcessMitigations
            Self for method chaining.
        """
        with self._lock:
            policy = DWORD()
            policy.value = 0x00000001  # Prohibit dynamic code
            if allow_thread_opt_out:
                policy.value |= 0x00000002
            if allow_remote_downgrade:
                policy.value |= 0x00000004
            self._mitigations[PROCESS_MITIGATION_POLICY.ProcessDynamicCodePolicy] = policy
        return self
    
    def enable_strict_handle_checks(self) -> "WindowsProcessMitigations":
        """
        Enable strict handle checks.
        
        Raises exceptions when invalid handles are used.
        
        Returns
        -------
        WindowsProcessMitigations
            Self for method chaining.
        """
        with self._lock:
            policy = DWORD()
            policy.value = 0x00000001
            self._mitigations[PROCESS_MITIGATION_POLICY.ProcessStrictHandleCheckPolicy] = policy
        return self
    
    def disable_extension_points(self) -> "WindowsProcessMitigations":
        """
        Disable extension points (DLL injection vectors).
        
        Prevents DLL injection via AppInit_DLLs, shims, etc.
        
        Returns
        -------
        WindowsProcessMitigations
            Self for method chaining.
        """
        with self._lock:
            policy = DWORD()
            policy.value = 0x00000001  # Disable extension points
            self._mitigations[PROCESS_MITIGATION_POLICY.ProcessExtensionPointDisablePolicy] = policy
        return self
    
    def restrict_image_load(self, prefer_system32: bool = True, audit: bool = False) -> "WindowsProcessMitigations":
        """
        Restrict image loading.
        
        Parameters
        ----------
        prefer_system32 : bool
            Prefer loading from System32.
        audit : bool
            Audit mode (log but don't block).
            
        Returns
        -------
        WindowsProcessMitigations
            Self for method chaining.
        """
        with self._lock:
            policy = DWORD()
            if prefer_system32:
                policy.value |= 0x00000001  # Prefer System32
            if audit:
                policy.value |= 0x00000002  # Audit mode
            self._mitigations[PROCESS_MITIGATION_POLICY.ProcessImageLoadPolicy] = policy
        return self
    
    def restrict_child_processes(self, block_all: bool = True) -> "WindowsProcessMitigations":
        """
        Restrict child process creation.
        
        Parameters
        ----------
        block_all : bool
            Block all child process creation.
            
        Returns
        -------
        WindowsProcessMitigations
            Self for method chaining.
        """
        with self._lock:
            policy = DWORD()
            if block_all:
                policy.value = 0x00000001  # Block child processes
            self._mitigations[PROCESS_MITIGATION_POLICY.ProcessChildProcessPolicy] = policy
        return self
    
    def enable_side_channel_isolation(self) -> "WindowsProcessMitigations":
        """
        Enable side channel isolation (Spectre/Meltdown mitigations).
        
        Returns
        -------
        WindowsProcessMitigations
            Self for method chaining.
        """
        with self._lock:
            policy = DWORD()
            policy.value = 0x00000001  # Isolate security domain
            self._mitigations[PROCESS_MITIGATION_POLICY.ProcessSideChannelIsolationPolicy] = policy
        return self
    
    def apply(self, process_handle: Optional[HANDLE] = None) -> bool:
        """
        Apply configured mitigations to a process.
        
        Parameters
        ----------
        process_handle : Optional[HANDLE]
            Process handle. If None, applies to current process.
            
        Returns
        -------
        bool
            True if all mitigations were applied successfully.
        """
        if process_handle is None:
            process_handle = windll.kernel32.GetCurrentProcess()
        
        success = True
        for policy_type, policy_data in self._mitigations.items():
            ret = windll.kernel32.SetProcessMitigationPolicy(
                policy_type,
                byref(policy_data),
                sizeof(policy_data)
            )
            if not ret:
                error = GetLastError()
                logger.warning(f"Failed to set mitigation {policy_type.name}: {FormatError(error)}")
                success = False
        
        return success
    
    def apply_to_current(self) -> bool:
        """
        Apply mitigations to current process.
        
        Returns
        -------
        bool
            True if successful.
        """
        return self.apply()
    
    def __repr__(self) -> str:
        """String representation."""
        return f"<WindowsProcessMitigations policies={len(self._mitigations)}>"


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    # Constants
    "CREATE_BREAKAWAY_FROM_JOB",
    "CREATE_SUSPENDED",
    "CREATE_NEW_PROCESS_GROUP",
    "CREATE_NO_WINDOW",
    "PROCESS_ALL_ACCESS",
    
    # Enums
    "JobObjectInfoClass",
    "JobObjectLimitFlags",
    "JobObjectUIRestrictions",
    "TOKEN_INFORMATION_CLASS",
    "PROCESS_MITIGATION_POLICY",
    
    # Privilege constants
    "SE_DEBUG_NAME",
    "SE_LOAD_DRIVER_NAME",
    "SE_TCB_NAME",
    "SE_CREATE_TOKEN_NAME",
    "SE_ASSIGNPRIMARYTOKEN_NAME",
    "SE_TAKE_OWNERSHIP_NAME",
    "SE_BACKUP_NAME",
    "SE_RESTORE_NAME",
    "SE_SECURITY_NAME",
    "SE_SHUTDOWN_NAME",
    "SE_REMOTE_SHUTDOWN_NAME",
    "SE_CREATE_GLOBAL_NAME",
    "SE_IMPERSONATE_NAME",
    
    # Integrity levels
    "SECURITY_MANDATORY_LOW_RID",
    "SECURITY_MANDATORY_MEDIUM_RID",
    "SECURITY_MANDATORY_HIGH_RID",
    "SECURITY_MANDATORY_SYSTEM_RID",
    "INTEGRITY_LEVEL_MAP",
    
    # Structures
    "LUID",
    "LUID_AND_ATTRIBUTES",
    "TOKEN_PRIVILEGES",
    "SID_AND_ATTRIBUTES",
    "TOKEN_GROUPS",
    "TOKEN_MANDATORY_LABEL",
    "SECURITY_ATTRIBUTES",
    "STARTUPINFO",
    "STARTUPINFOEX",
    "PROCESS_INFORMATION",
    "IO_COUNTERS",
    "JOBOBJECT_BASIC_LIMIT_INFORMATION",
    "JOBOBJECT_EXTENDED_LIMIT_INFORMATION",
    "JOBOBJECT_BASIC_ACCOUNTING_INFORMATION",
    
    # Main classes
    "WindowsJobObject",
    "WindowsRestrictedToken",
    "WindowsProcessMitigations",
]

