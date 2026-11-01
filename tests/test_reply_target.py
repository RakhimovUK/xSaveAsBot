from datetime import UTC, datetime

from aiogram.types import CallbackQuery

from app.bot.reply_target import ReplyTarget

SUPERGROUP = -1002000000000


def test_private_chat(msg_factory):
    t = ReplyTarget.from_message(msg_factory(chat_id=42, chat_type="private", message_id=5))
    assert t == ReplyTarget(chat_id=42, message_thread_id=None, reply_to_message_id=5)


def test_normal_group_reply_chain_thread_is_ignored(msg_factory):
    # In non-forum groups Telegram sets message_thread_id for reply chains; must be dropped.
    m = msg_factory(chat_id=-100, chat_type="group", thread_id=7, is_topic=None)
    assert ReplyTarget.from_message(m).message_thread_id is None


def test_forum_general_topic_has_no_thread(msg_factory):
    m = msg_factory(chat_id=SUPERGROUP, chat_type="supergroup", is_forum=True)
    t = ReplyTarget.from_message(m)
    assert t.chat_id == SUPERGROUP
    assert t.message_thread_id is None


def test_forum_topic_keeps_thread(msg_factory):
    m = msg_factory(
        chat_id=SUPERGROUP,
        chat_type="supergroup",
        is_forum=True,
        thread_id=55,
        is_topic=True,
        message_id=900,
    )
    t = ReplyTarget.from_message(m)
    assert t == ReplyTarget(chat_id=SUPERGROUP, message_thread_id=55, reply_to_message_id=900)


def test_forum_reply_inside_general_is_not_a_topic(msg_factory):
    m = msg_factory(chat_type="supergroup", is_forum=True, thread_id=3, is_topic=False)
    assert ReplyTarget.from_message(m).message_thread_id is None


def test_callback_in_topic_stays_in_topic_and_replies_to_original(msg_factory):
    user_link = {
        "message_id": 900,
        "date": datetime.now(UTC),
        "chat": {"id": SUPERGROUP, "type": "supergroup", "is_forum": True},
        "message_thread_id": 55,
        "is_topic_message": True,
        "text": "https://youtu.be/x",
    }
    keyboard_msg = msg_factory(
        chat_id=SUPERGROUP,
        chat_type="supergroup",
        is_forum=True,
        thread_id=55,
        is_topic=True,
        message_id=901,
        reply_to=user_link,
    )
    cb = CallbackQuery(
        id="1",
        from_user={"id": 42, "is_bot": False, "first_name": "U"},
        chat_instance="ci",
        message=keyboard_msg,
        data="q:720",
    )
    t = ReplyTarget.from_callback(cb)
    assert t == ReplyTarget(chat_id=SUPERGROUP, message_thread_id=55, reply_to_message_id=900)


def test_callback_from_inline_message():
    cb = CallbackQuery(
        id="1",
        from_user={"id": 42, "is_bot": False, "first_name": "U"},
        chat_instance="ci",
        inline_message_id="AAA",
        data="x",
    )
    t = ReplyTarget.from_callback(cb)
    assert t.is_inline and t.inline_message_id == "AAA"


def test_json_roundtrip():
    t = ReplyTarget(
        chat_id=SUPERGROUP,
        message_thread_id=55,
        reply_to_message_id=9,
        fallback_without_thread=True,
    )
    assert ReplyTarget.from_json(t.to_json()) == t
