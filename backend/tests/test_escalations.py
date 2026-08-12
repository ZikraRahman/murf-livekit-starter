import asyncio
from types import SimpleNamespace

import agent as agent_module


def _tool(assistant: agent_module.Assistant, name: str):
    return next(tool for tool in assistant.tools if tool._info.name == name)


def _context(*user_messages: str) -> SimpleNamespace:
    messages = [
        SimpleNamespace(role="user", text_content=message) for message in user_messages
    ]
    return SimpleNamespace(
        session=SimpleNamespace(history=SimpleNamespace(messages=lambda: messages))
    )


def _prepare_fraud_consent(assistant: agent_module.Assistant) -> None:
    result = asyncio.run(
        _tool(assistant, "prepare_escalation_consent")._func(
            assistant,
            _context("I do not recognize a UPI payment."),
            what_happened="Caller reported an unrecognized UPI payment.",
            what_agent_checked="Explained immediate fraud-safety steps.",
            urgency="high",
            caller_language="English",
            preferred_follow_up="phone call",
        )
    )
    assert result["prepared"] == "true"


def _create(
    assistant: agent_module.Assistant,
    context: SimpleNamespace,
    *,
    permission_confirmed: bool = True,
):
    return asyncio.run(
        _tool(assistant, "create_escalation")._func(
            assistant,
            context,
            permission_confirmed=permission_confirmed,
        )
    )


def test_fraud_preparation_creates_no_request_before_permission(monkeypatch) -> None:
    created: list[dict[str, object]] = []
    monkeypatch.setattr(
        agent_module,
        "create_escalation_request",
        lambda **kwargs: created.append(kwargs),
    )
    assistant = agent_module.Assistant(user_id="caller-1")

    _prepare_fraud_consent(assistant)

    assert created == []


def test_fraud_refusal_creates_no_request(monkeypatch) -> None:
    created: list[dict[str, object]] = []
    monkeypatch.setattr(
        agent_module,
        "create_escalation_request",
        lambda **kwargs: created.append(kwargs),
    )
    assistant = agent_module.Assistant(user_id="caller-1")
    _prepare_fraud_consent(assistant)

    result = _create(
        assistant,
        _context("I do not recognize a UPI payment.", "No, do not share it."),
    )

    assert result["created"] == "false"
    assert created == []


def test_fraud_yes_creates_exactly_one_request_and_returns_reference(
    monkeypatch,
) -> None:
    created: list[dict[str, object]] = []

    def fake_create(**kwargs):
        created.append(kwargs)
        return {"reference_id": "ESC-20260812-ABC123", **kwargs}

    monkeypatch.setattr(agent_module, "create_escalation_request", fake_create)
    monkeypatch.setattr(
        agent_module, "get_user", lambda user_id: {"name": "Ramesh", "facts": {}}
    )
    assistant = agent_module.Assistant(user_id="caller-1")
    _prepare_fraud_consent(assistant)

    result = _create(
        assistant,
        _context("I do not recognize a UPI payment.", "Yes, you can share it."),
    )
    duplicate_attempt = _create(
        assistant,
        _context("I do not recognize a UPI payment.", "Yes, you can share it."),
    )

    assert result == {"created": "true", "reference_id": "ESC-20260812-ABC123"}
    assert duplicate_attempt["created"] == "false"
    assert len(created) == 1
    assert created[0]["who_needs_help"] == "Ramesh"


def test_financial_decision_requires_later_permission(monkeypatch) -> None:
    created: list[dict[str, object]] = []
    monkeypatch.setattr(
        agent_module,
        "create_escalation_request",
        lambda **kwargs: created.append(kwargs),
    )
    assistant = agent_module.Assistant(user_id="caller-1")
    prepared = asyncio.run(
        _tool(assistant, "prepare_escalation_consent")._func(
            assistant,
            _context("Please approve my loan application."),
            what_happened="Caller asked the assistant to approve a loan.",
            what_agent_checked="Explained that the assistant cannot make loan decisions.",
            urgency="normal",
            caller_language="English",
            preferred_follow_up="phone call",
        )
    )

    result = _create(assistant, _context("Please approve my loan application."))

    assert prepared["prepared"] == "true"
    assert result["created"] == "false"
    assert created == []


def test_direct_create_without_confirmed_permission_refuses(monkeypatch) -> None:
    created: list[dict[str, object]] = []
    monkeypatch.setattr(
        agent_module,
        "create_escalation_request",
        lambda **kwargs: created.append(kwargs),
    )
    assistant = agent_module.Assistant(user_id="caller-1")

    result = _create(assistant, _context("Yes, you can share it."))

    assert result["created"] == "false"
    assert created == []


def test_create_refuses_when_permission_flag_is_not_confirmed(monkeypatch) -> None:
    created: list[dict[str, object]] = []
    monkeypatch.setattr(
        agent_module,
        "create_escalation_request",
        lambda **kwargs: created.append(kwargs),
    )
    assistant = agent_module.Assistant(user_id="caller-1")
    _prepare_fraud_consent(assistant)

    result = _create(
        assistant,
        _context("I do not recognize a UPI payment.", "Yes, you can share it."),
        permission_confirmed=False,
    )

    assert result["created"] == "false"
    assert created == []


def test_yes_flow_persists_to_the_runtime_database_shape(tmp_path, monkeypatch) -> None:
    import memory

    monkeypatch.setattr(memory, "DATABASE_PATH", tmp_path / "memory.db")
    assistant = agent_module.Assistant(user_id="caller-1")
    _prepare_fraud_consent(assistant)

    result = _create(
        assistant,
        _context("I do not recognize a UPI payment.", "Yes, you can share it."),
    )
    saved = memory.get_escalation_request(result["reference_id"])

    assert result["created"] == "true"
    assert saved is not None
    assert saved["user_id"] == "caller-1"
    assert saved["what_happened"] == "Caller reported an unrecognized UPI payment."


def test_persisted_escalation_can_be_inspected(tmp_path, monkeypatch) -> None:
    import memory

    monkeypatch.setattr(memory, "DATABASE_PATH", tmp_path / "memory.db")
    request = memory.create_escalation_request(
        user_id="caller-1",
        who_needs_help="Current caller",
        what_happened="Possible unauthorized transaction.",
        what_agent_checked="Explained bank-contact steps.",
        urgency="high",
        caller_language="English",
        preferred_follow_up="phone call",
    )

    saved = memory.get_escalation_request(request["reference_id"])
    open_requests = memory.list_escalation_requests()

    assert saved is not None
    assert saved["reference_id"] == request["reference_id"]
    assert saved["status"] == "open"
    assert open_requests == [
        {
            "reference_id": request["reference_id"],
            "who_needs_help": "Current caller",
            "what_happened": "Possible unauthorized transaction.",
            "what_agent_checked": "Explained bank-contact steps.",
            "urgency": "high",
            "caller_language": "English",
            "preferred_follow_up": "phone call",
            "status": "open",
            "created_at": request["created_at"],
        }
    ]
