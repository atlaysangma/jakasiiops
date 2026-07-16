from __future__ import annotations

import ctypes
import getpass
import os
import re
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, Callable, MutableMapping, Protocol


ENVIRONMENT_NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")


class CredentialVault(Protocol):
    def write(self, store_id: str, name: str, secret: str) -> None: ...

    def read(self, store_id: str, name: str) -> str | None: ...


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


@dataclass(slots=True)
class WindowsCredentialVault:
    """Store collector secrets in the current user's Windows credential vault."""

    prefix: str = "JAKASII_OPS"

    @staticmethod
    def _safe_store_id(store_id: str) -> str:
        value = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(store_id).strip())
        if not value:
            raise ValueError("A non-empty store ID is required.")
        return value[:128]

    @staticmethod
    def _safe_name(name: str) -> str:
        if not ENVIRONMENT_NAME.fullmatch(str(name)):
            raise ValueError("Credential names must be uppercase environment names.")
        return str(name)

    def _target(self, store_id: str, name: str) -> str:
        return f"{self.prefix}/{self._safe_store_id(store_id)}/{self._safe_name(name)}"

    @staticmethod
    def _api() -> Any:
        if os.name != "nt":
            raise OSError("Windows Credential Manager is available only on Windows.")
        api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        api.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
        api.CredWriteW.restype = wintypes.BOOL
        api.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)),
        ]
        api.CredReadW.restype = wintypes.BOOL
        api.CredFree.argtypes = [ctypes.c_void_p]
        api.CredFree.restype = None
        return api

    def write(self, store_id: str, name: str, secret: str) -> None:
        if not secret:
            raise ValueError("An empty secret cannot be stored.")
        target = self._target(store_id, name)
        blob = secret.encode("utf-16-le")
        buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        credential = _CREDENTIALW()
        credential.Type = 1  # CRED_TYPE_GENERIC
        credential.TargetName = target
        credential.Comment = "JAKASII Ops local collector credential"
        credential.CredentialBlobSize = len(blob)
        credential.CredentialBlob = ctypes.cast(
            buffer, ctypes.POINTER(ctypes.c_ubyte)
        )
        credential.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE for this Windows user
        credential.UserName = self._safe_store_id(store_id)
        if not self._api().CredWriteW(ctypes.byref(credential), 0):
            raise ctypes.WinError()

    def read(self, store_id: str, name: str) -> str | None:
        target = self._target(store_id, name)
        pointer = ctypes.POINTER(_CREDENTIALW)()
        api = self._api()
        if not api.CredReadW(target, 1, 0, ctypes.byref(pointer)):
            error = ctypes.get_last_error()
            if error == 1168:  # ERROR_NOT_FOUND
                return None
            raise ctypes.WinError(error)
        try:
            credential = pointer.contents
            blob = ctypes.string_at(
                credential.CredentialBlob, credential.CredentialBlobSize
            )
            return blob.decode("utf-16-le")
        finally:
            api.CredFree(pointer)


def manifest_secret_names(manifest: dict[str, Any] | None) -> list[str]:
    if not manifest:
        return []
    names = manifest.get("required_environment", [])
    if not isinstance(names, list) or not all(
        isinstance(item, str) and ENVIRONMENT_NAME.fullmatch(item) for item in names
    ):
        raise ValueError("Collector manifest contains invalid credential names.")
    return list(dict.fromkeys(names))


def configure_manifest_credentials(
    store_id: str,
    manifest: dict[str, Any],
    *,
    vault: CredentialVault | None = None,
    prompt: Callable[[str], str] = getpass.getpass,
) -> dict[str, Any]:
    vault = vault or WindowsCredentialVault()
    stored: list[str] = []
    for name in manifest_secret_names(manifest):
        secret = prompt(f"Enter {name} for the local camera collector: ")
        vault.write(store_id, name, secret)
        stored.append(name)
    return {"stored_names": stored, "secret_values_returned": False}


def hydrate_manifest_environment(
    store_id: str,
    manifest: dict[str, Any] | None,
    *,
    vault: CredentialVault | None = None,
    environment: MutableMapping[str, str] | None = None,
) -> dict[str, Any]:
    vault = vault or WindowsCredentialVault()
    environment = environment if environment is not None else os.environ
    loaded: list[str] = []
    missing: list[str] = []
    for name in manifest_secret_names(manifest):
        if environment.get(name, "").strip():
            loaded.append(name)
            continue
        secret = vault.read(store_id, name)
        if secret:
            environment[name] = secret
            loaded.append(name)
        else:
            missing.append(name)
    return {
        "available_names": loaded,
        "missing_names": missing,
        "secret_values_returned": False,
    }
