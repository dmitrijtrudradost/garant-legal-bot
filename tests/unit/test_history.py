from core.history import InMemoryDialogueHistory
from core.models import DialogueEntry


def test_get_creates_history_with_system_prompt():
    history = InMemoryDialogueHistory()
    entries = history.get("peer1")

    assert len(entries) == 1
    assert entries[0].role == "system"


def test_exists_reflects_creation():
    history = InMemoryDialogueHistory()
    assert history.exists("peer1") is False

    history.get("peer1")
    assert history.exists("peer1") is True


def test_add_appends_message():
    history = InMemoryDialogueHistory()
    history.add("peer1", DialogueEntry(role="user", content="Привет"))

    entries = history.get("peer1")
    assert entries[-1].content == "Привет"
    assert entries[-1].role == "user"


def test_history_is_trimmed_to_limit():
    history = InMemoryDialogueHistory(max_messages=4)
    for i in range(10):
        history.add("peer1", DialogueEntry(role="user", content=f"msg{i}"))

    entries = history.get("peer1")
    assert entries[0].role == "system"  # системное сообщение сохраняется всегда
    assert len(entries) == 5  # system + 4 последних
    assert entries[-1].content == "msg9"
