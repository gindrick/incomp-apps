"""Chyby aplikace s kódy, kterým rozumí frontend (``e.code``)."""
from __future__ import annotations


class AppError(Exception):
    code = "internal"
    status = 500

    def __init__(self, message: str = "", **extra):
        super().__init__(message or self.code)
        self.message = message or self.code
        self.extra = extra

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, **self.extra}


class InvalidArgument(AppError):
    code, status = "invalid_argument", 400


class NotFound(AppError):
    code, status = "not_found", 404


class PermissionDenied(AppError):
    code, status = "permission_denied", 403


class Unauthenticated(AppError):
    # frontend u příloh hlásí "Přihlášení vypršelo, načti stránku znovu"
    code, status = "upstream_auth", 401


class VersionConflict(AppError):
    code, status = "failed_precondition", 409


class TooLarge(AppError):
    code, status = "too_large", 413


class UnsupportedType(AppError):
    code, status = "unsupported_type", 415
