"""Extractor errors. `code` maps to the `err-<code>` i18n message shown to the user."""

from __future__ import annotations


class ExtractError(Exception):
    code = "generic"

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class UnsupportedError(ExtractError):
    code = "unsupported"


class PrivateError(ExtractError):
    code = "private"


class NotFoundError(ExtractError):
    code = "notfound"


class AgeRestrictedError(ExtractError):
    code = "age"


class BotCheckError(ExtractError):
    """Platform blocked our IP ("confirm you're not a bot"). Relay can still get it."""

    code = "unavailable"


class LoginRequiredError(ExtractError):
    code = "unavailable"


class TooLargeError(ExtractError):
    code = "toolarge"


class TooLongError(ExtractError):
    code = "toolong"


class TemporaryError(ExtractError):
    code = "unavailable"


# Failures where asking a helper bot may still succeed. Private / deleted posts will not.
RELAYABLE = (
    BotCheckError,
    LoginRequiredError,
    AgeRestrictedError,
    UnsupportedError,
    TemporaryError,
    ExtractError,
)
NOT_RELAYABLE = (PrivateError, NotFoundError, TooLongError)


def is_relayable(exc: BaseException) -> bool:
    return isinstance(exc, ExtractError) and not isinstance(exc, NOT_RELAYABLE)


def classify(message: str) -> ExtractError:
    """Turn a yt-dlp / HTTP error text into a typed error."""
    low = message.lower()
    if "sign in to confirm" in low or "not a bot" in low:
        return BotCheckError(message)
    if "unsupported url" in low:
        return UnsupportedError(message)
    if "private" in low and ("video" in low or "account" in low or "post" in low or "is " in low):
        return PrivateError(message)
    if "age" in low and ("restrict" in low or "confirm your age" in low or "verify" in low):
        return AgeRestrictedError(message)
    if any(
        marker in low
        for marker in (
            "login required",
            "log in",
            "logged-in",
            "authentication is required",
            "requires authentication",
            "use --cookies",
            "rate-limit",
        )
    ):
        return LoginRequiredError(message)
    if any(
        marker in low
        for marker in (
            "not found",
            "404",
            "does not exist",
            "has been removed",
            "has been deleted",
            "video unavailable",
            "no video could be found",
            "no media",
        )
    ):
        return NotFoundError(message)
    if any(
        marker in low
        for marker in ("timed out", "timeout", "connection", "http error 5", "429", "temporarily")
    ):
        return TemporaryError(message)
    return ExtractError(message)
