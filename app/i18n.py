"""Fluent-based i18n. Strings live in app/locales/<lang>/*.ftl."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from fluent.runtime import FluentBundle, FluentResource

from app.config import SUPPORTED_LANGS

log = logging.getLogger(__name__)

LOCALES_DIR = Path(__file__).parent / "locales"
FALLBACK_LANG = "uz"


@lru_cache
def _bundle(lang: str) -> FluentBundle:
    bundle = FluentBundle([lang], use_isolating=False)
    for path in sorted((LOCALES_DIR / lang).glob("*.ftl")):
        bundle.add_resource(FluentResource(path.read_text(encoding="utf-8")))
    return bundle


def message_ids(lang: str) -> set[str]:
    ids: set[str] = set()
    for path in (LOCALES_DIR / lang).glob("*.ftl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line and not line[0].isspace() and not line.startswith("#") and "=" in line:
                ids.add(line.split("=", 1)[0].strip())
    return ids


def normalize_lang(code: str | None, default: str = FALLBACK_LANG) -> str:
    if not code:
        return default
    short = code.split("-")[0].lower()
    return short if short in SUPPORTED_LANGS else default


def gettext(lang: str, key: str, **args: Any) -> str:
    for candidate in (lang, FALLBACK_LANG):
        bundle = _bundle(candidate)
        if bundle.has_message(key):
            msg = bundle.get_message(key)
            if msg.value is None:
                break
            text, errors = bundle.format_pattern(msg.value, args)
            for err in errors:
                log.warning("i18n %s/%s: %s", candidate, key, err)
            return text
    log.error("Missing i18n key %r for lang %r", key, lang)
    return key


class Translator:
    """Per-update translator injected into handlers as `t`."""

    def __init__(self, lang: str) -> None:
        self.lang = lang

    def __call__(self, key: str, **args: Any) -> str:
        return gettext(self.lang, key, **args)
