"""Enforce section 2a: outgoing bot messages only via app/bot/sender.py."""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"

ALLOWED_FILES = {
    APP / "bot" / "sender.py",
}
# The uploader talks MTProto (Telethon), not the Bot API.
ALLOWED_DIRS = {APP / "uploader"}

BANNED_EXACT = {
    "copy_message",
    "copy_messages",
    "forward_message",
    "forward_messages",
    "copy_to",
    "forward",
    "reply",
    "send_copy",
}
# Methods that look like sends but are fine anywhere
ALLOWED_ANSWERS = {
    "answer_callback_query",
    "answer_inline_query",
    "answer_pre_checkout_query",
    "answer_shipping_query",
    "answer_web_app_query",
}
MESSAGE_LIKE_NAMES = ("message", "msg")


def _is_banned(call: ast.Call) -> bool:
    func = call.func
    if not isinstance(func, ast.Attribute):
        return False
    name = func.attr
    if name in ALLOWED_ANSWERS:
        return False
    if name.startswith("send_") or name.startswith("reply_") or name in BANNED_EXACT:
        return True
    if name.startswith("answer_"):
        return True  # message.answer_photo(...) etc.
    if name == "answer":
        # callback.answer() / inline_query.answer() are fine; message.answer() is not
        receiver = func.value
        rname = (
            receiver.attr if isinstance(receiver, ast.Attribute) else getattr(receiver, "id", "")
        )
        return any(m in rname.lower() for m in MESSAGE_LIKE_NAMES)
    return False


def test_no_raw_send_calls_outside_sender():
    offenders = []
    for path in APP.rglob("*.py"):
        if path in ALLOWED_FILES or any(d in path.parents for d in ALLOWED_DIRS):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_banned(node):
                offenders.append(f"{path.relative_to(APP.parent)}:{node.lineno}")
    assert not offenders, "Use app.bot.sender.Sender instead of raw sends:\n" + "\n".join(offenders)


def test_checker_catches_examples():
    for src in (
        "bot.send_message(1, 'x')",
        "message.answer('x')",
        "message.reply('x')",
        "msg.answer_photo(p)",
        "bot.copy_message(1, 2, 3)",
    ):
        assert _is_banned(ast.parse(src).body[0].value), src
    for src in ("callback.answer('x')", "bot.answer_callback_query('1')", "query.answer([])"):
        assert not _is_banned(ast.parse(src).body[0].value), src
