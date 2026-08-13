import asyncio
import json
import sqlite3
import threading
from urllib.request import Request, urlopen

import agent
import memory
import memory_api


def test_call_records_are_created_and_aggregated(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "memory.db"
    monkeypatch.setattr(memory, "DATABASE_PATH", database_path)

    memory.init_db()
    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert "call_records" in tables

    assert memory.record_call(
        call_id="call-success", user_id="caller-1", outcome="success"
    )
    assert memory.record_call(
        call_id="call-failed", user_id="caller-1", outcome="failed"
    )
    assert not memory.record_call(
        call_id="call-success", user_id="caller-1", outcome="success"
    )
    assert memory.get_call_analytics() == {
        "total_calls": 2,
        "successful_calls": 1,
        "failed_calls": 1,
    }


def test_analytics_api_returns_database_aggregates(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(memory, "DATABASE_PATH", tmp_path / "memory.db")
    monkeypatch.setenv("MEMORY_API_PORT", "0")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "analytics-test-secret")
    memory.record_call(call_id="call-1", user_id="caller-1", outcome="success")
    memory.record_call(call_id="call-2", user_id="caller-2", outcome="failed")

    server = memory_api.create_server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/analytics",
            headers={"X-Memory-Secret": "analytics-test-secret"},
        )
        with urlopen(request) as response:
            payload = json.loads(response.read())
        assert payload == {
            "total_calls": 2,
            "successful_calls": 1,
            "failed_calls": 1,
        }
    finally:
        server.shutdown()
        server.server_close()


def test_scheme_enquiry_success_is_explicit() -> None:
    assistant = agent.Assistant(user_id="caller-1")
    tool = next(
        tool
        for tool in assistant.tools
        if tool._info.name == "mark_scheme_enquiry_complete"
    )

    assert not assistant.call_successful
    result = asyncio.run(tool._func(assistant, None))

    assert result == {"call_successful": "true"}
    assert assistant.call_successful
