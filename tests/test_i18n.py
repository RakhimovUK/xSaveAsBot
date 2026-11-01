from app.config import SUPPORTED_LANGS
from app.i18n import Translator, gettext, message_ids, normalize_lang


def test_all_locales_have_same_keys():
    base = message_ids("uz")
    assert base
    for lang in SUPPORTED_LANGS:
        assert message_ids(lang) == base, lang


def test_format_args_in_each_language():
    for lang in SUPPORTED_LANGS:
        text = Translator(lang)("welcome", name="Ali")
        assert "Ali" in text and "{" not in text


def test_languages_differ():
    assert len({gettext(lang, "lang-name") for lang in SUPPORTED_LANGS}) == 3


def test_missing_key_returns_key():
    assert gettext("en", "no-such-key") == "no-such-key"


def test_normalize_lang():
    assert normalize_lang("ru-RU") == "ru"
    assert normalize_lang("de") == "uz"
    assert normalize_lang(None, "en") == "en"
