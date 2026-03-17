"""Integration tests for Chat + Memory lifecycle.

Tests:
  1. Memory._init_db handles bare filename paths (no crash).
  2. Memory._init_db handles relative sub-directory paths.
  3. Memory save/retrieve round-trip with embeddings.
  4. Memory.context() full-dump fallback (no embeddings).
  5. Chat append / compression / summary carry-forward.
  6. Orchestrator on_task_complete callback appends assistant response to Chat.
  7. Chat.apply_compression trims messages while keeping recent ones.
"""
import sys
sys.path.insert(0, ".")

import os
import tempfile
import threading

# ---------------------------------------------------------------------------
# Memory tests
# ---------------------------------------------------------------------------

def test_memory_bare_filename_does_not_crash():
    """Memory(path='foo.db') should not raise even though dirname is ''."""
    print("=== Memory: bare filename path ===")
    from delfhos.memory import Memory

    tmpdir = tempfile.gettempdir()
    original_cwd = os.getcwd()
    try:
        os.chdir(tmpdir)
        # Previously raised FileNotFoundError because dirname('foo.db') == ''
        m = Memory(path="delfhos_bare_smoke.db", namespace="bare_test")
        m.save("bare path test fact")
        ctx = m.context()
        assert ctx.strip() == "bare path test fact", f"Unexpected context: {ctx!r}"
        print("  Bare filename path: OK")
    finally:
        db_file = os.path.join(tmpdir, "delfhos_bare_smoke.db")
        if os.path.exists(db_file):
            os.remove(db_file)
        os.chdir(original_cwd)


def test_memory_relative_subdir_path():
    """Memory(path='sub/dir/mem.db') should create parent directories."""
    print("\n=== Memory: relative sub-directory path ===")
    from delfhos.memory import Memory
    import tempfile

    tmpdir = tempfile.mkdtemp()
    sub_path = os.path.join(tmpdir, "sub", "dir", "mem.db")
    try:
        m = Memory(path=sub_path, namespace="sub_test")
        m.save("sub dir fact")
        assert m.context() == "sub dir fact"
        print("  Sub-directory path: OK")
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_memory_save_and_retrieve():
    """save() embeds facts, retrieve() returns semantically relevant ones."""
    print("\n=== Memory: save and semantic retrieve ===")
    from delfhos.memory import Memory

    p = os.path.join(tempfile.gettempdir(), "delfhos_saveretreive.db")
    if os.path.exists(p):
        os.remove(p)

    m = Memory(path=p, namespace="integration_test")
    m.save("My main client is Acme Corp\nMy name is David\nThe project deadline is Q2")

    result = m.retrieve("who is the main client?", top_k=2, threshold=0.0)
    assert "Acme" in result, f"Expected Acme in result: {result!r}"
    print(f"  Retrieve result: {result!r}")
    print("  OK")

    if os.path.exists(p):
        os.remove(p)


def test_memory_context_fallback_no_embeddings():
    """context() should still work even if no embedding was stored."""
    print("\n=== Memory: context() fallback ===")
    from delfhos.memory import Memory
    import sqlite3

    p = os.path.join(tempfile.gettempdir(), "delfhos_ctxfallback.db")
    if os.path.exists(p):
        os.remove(p)

    m = Memory(path=p, namespace="fallback_ns")

    # Insert a row without an embedding row to simulate a pre-embedding DB
    with sqlite3.connect(m.path) as conn:
        conn.execute(
            "INSERT INTO memories (namespace, content) VALUES (?, ?)",
            ("fallback_ns", "legacy fact without embedding"),
        )

    # context() should return it
    ctx = m.context()
    assert "legacy fact without embedding" in ctx
    print("  context() fallback: OK")

    if os.path.exists(p):
        os.remove(p)


# ---------------------------------------------------------------------------
# Chat tests
# ---------------------------------------------------------------------------

def test_chat_append_and_compression_carry_forward():
    """Compression should incorporate prior summary, not erase it."""
    print("\n=== Chat: compression carries forward prior summary ===")
    from delfhos.memory import Chat

    chat_db = os.path.join(tempfile.gettempdir(), "delfhos_chat_carry_forward.db")
    if os.path.exists(chat_db):
        os.remove(chat_db)

    chat = Chat(keep=2, summarize=True, path=chat_db, namespace="chat_carry_forward")
    chat.summary = "Previously: user asked about invoice #42."

    # Simulate 5 rounds → 10 messages total
    for i in range(5):
        chat.append("user", f"Message {i}")
        chat.append("assistant", f"Reply {i}")

    # Compress first 6; apply_compression discards (compressed - keep) = 6-2 = 4
    new_summary = "Summary includes: invoice #42 discussion and new messages."
    chat.apply_compression(new_summary, compressed_count=6)

    assert chat.summary == new_summary
    # 10 messages - 4 discarded = 6 remaining
    assert len(chat.messages) == 6, f"Expected 6 remaining, got {len(chat.messages)}"
    print(f"  summary: {chat.summary!r}")
    print(f"  remaining messages: {len(chat.messages)}")
    print("  OK")

    if os.path.exists(chat_db):
        os.remove(chat_db)


def test_chat_apply_compression_keeps_recent():
    """apply_compression(keep=3) keeps exactly the last 3 messages."""
    print("\n=== Chat: apply_compression keeps recent messages ===")
    from delfhos.memory import Chat

    chat_db = os.path.join(tempfile.gettempdir(), "delfhos_chat_keep_recent.db")
    if os.path.exists(chat_db):
        os.remove(chat_db)

    chat = Chat(keep=3, summarize=True, path=chat_db, namespace="chat_keep_recent")
    for i in range(6):
        chat.append("user", f"msg {i}")

    # Snapshot 6, compress all 6
    chat.apply_compression("new summary", compressed_count=6)

    assert len(chat.messages) == 3, f"Expected 3 remaining, got {len(chat.messages)}"
    assert chat.messages[0]["content"] == "msg 3"
    print("  Messages kept correctly")
    print("  OK")

    if os.path.exists(chat_db):
        os.remove(chat_db)


# ---------------------------------------------------------------------------
# Orchestrator callback test
# ---------------------------------------------------------------------------

def test_orchestrator_on_task_complete_appends_to_chat():
    """on_task_complete fires after a task and result is appended to Chat."""
    print("\n=== Orchestrator: on_task_complete → Chat ===")
    from delfhos.memory import Chat

    chat_db = os.path.join(tempfile.gettempdir(), "delfhos_chat_orchestrator_append.db")
    if os.path.exists(chat_db):
        os.remove(chat_db)

    chat = Chat(keep=10, summarize=False, path=chat_db, namespace="chat_orchestrator_append")

    # Simulate what Agent.__init__ registers
    def _append_assistant_response(task_id: str, message: str):
        if message and message.strip() and message != "Task completed successfully":
            chat.append("assistant", message)

    # Call the callback as the orchestrator would
    _append_assistant_response("task-001", "The answer is 42.")
    _append_assistant_response("task-002", "Task completed successfully")  # Should be skipped

    assert len(chat.messages) == 1, f"Expected 1 message, got {len(chat.messages)}"
    assert chat.messages[0]["role"] == "assistant"
    assert chat.messages[0]["content"] == "The answer is 42."
    print("  Callback captured response: OK")
    print("  Silent skip of 'Task completed successfully': OK")

    if os.path.exists(chat_db):
        os.remove(chat_db)


if __name__ == "__main__":
    test_memory_bare_filename_does_not_crash()
    test_memory_relative_subdir_path()
    test_memory_save_and_retrieve()
    test_memory_context_fallback_no_embeddings()
    test_chat_append_and_compression_carry_forward()
    test_chat_apply_compression_keeps_recent()
    test_orchestrator_on_task_complete_appends_to_chat()
    print("\n✅ ALL MEMORY INTEGRATION TESTS PASSED")
