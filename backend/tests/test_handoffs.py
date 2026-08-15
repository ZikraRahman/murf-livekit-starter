import asyncio
from types import SimpleNamespace

from livekit.agents import ChatContext

import agent as agent_module


def _tool(assistant: agent_module.Assistant, name: str):
    return next(tool for tool in assistant.tools if tool._info.name == name)


class HandoffSession:
    def __init__(self, *user_messages: str) -> None:
        self.announcements: list[str] = []
        messages = [
            SimpleNamespace(role="user", text_content=message)
            for message in user_messages
        ]
        self.history = SimpleNamespace(messages=lambda: messages)

    async def say(self, text: str) -> None:
        self.announcements.append(text)


def _context(*user_messages: str) -> SimpleNamespace:
    return SimpleNamespace(session=HandoffSession(*user_messages))


def test_personal_finance_handoff_preserves_context_and_uses_samar(
    monkeypatch,
) -> None:
    tts_options: dict[str, object] = {}

    def fake_tts(**kwargs):
        tts_options.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(agent_module.murf, "TTS", fake_tts)
    active_agents: list[str] = []

    async def set_active_agent(agent_id: str) -> None:
        active_agents.append(agent_id)

    assistant = agent_module.Assistant(
        user_id="caller-1", set_active_agent=set_active_agent
    )

    context = _context("My salary is 30k and I need a budget.")
    specialist = asyncio.run(
        _tool(assistant, "handoff_to_personal_finance")._func(assistant, context)
    )

    assert isinstance(specialist, agent_module.PersonalFinanceSpecialist)
    assert "personal-finance planning" in specialist.instructions
    assert context.session.announcements == [
        "I'll connect you with our personal finance specialist who can help you build "
        "a practical budget."
    ]
    assert active_agents == ["connecting_personal_finance"]
    assert tts_options["voice"] == "Samar"
    assert tts_options["style"] == "Conversation"
    assert tts_options["text_pacing"] is True


def test_tax_gst_handoff_preserves_context_and_uses_pooja(monkeypatch) -> None:
    tts_options: dict[str, object] = {}

    def fake_tts(**kwargs):
        tts_options.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(agent_module.murf, "TTS", fake_tts)
    active_agents: list[str] = []

    async def set_active_agent(agent_id: str) -> None:
        active_agents.append(agent_id)

    assistant = agent_module.Assistant(
        user_id="caller-1", set_active_agent=set_active_agent
    )
    context = ChatContext.empty()
    context.add_message(
        role="user", content="Mujhe ITR file karna hai aur mere paas Form 16 hai."
    )
    asyncio.run(assistant.update_chat_ctx(context))

    handoff_context = _context("Mujhe ITR file karna hai. Process kya hai?")
    specialist = asyncio.run(
        _tool(assistant, "handoff_to_tax_gst")._func(assistant, handoff_context)
    )

    assert isinstance(specialist, agent_module.TaxGSTSpecialist)
    assert specialist.chat_ctx.messages()[0].text_content == (
        "Mujhe ITR file karna hai aur mere paas Form 16 hai."
    )
    assert handoff_context.session.announcements == [
        "मैं आपको हमारे tax और GST specialist से connect करती हूँ, जो इसमें आपकी मदद करेंगे।"
    ]
    assert active_agents == ["connecting_tax_gst"]
    assert tts_options["voice"] == "Pooja"
    assert tts_options["style"] == "Conversation"
    assert tts_options["text_pacing"] is True


def test_tax_specialist_returns_to_main_with_context(monkeypatch) -> None:
    monkeypatch.setattr(agent_module.murf, "TTS", lambda **kwargs: SimpleNamespace())
    context = ChatContext.empty()
    context.add_message(
        role="user", content="Actually government schemes ke baare mein batao."
    )
    active_agents: list[str] = []

    async def set_active_agent(agent_id: str) -> None:
        active_agents.append(agent_id)

    specialist = agent_module.TaxGSTSpecialist(
        context, user_id="caller-1", set_active_agent=set_active_agent
    )

    handback_context = _context("Actually government schemes ke baare mein batao.")
    main_agent = asyncio.run(
        next(
            tool
            for tool in specialist.tools
            if tool._info.name == "return_to_main_agent"
        )._func(specialist, handback_context)
    )

    assert isinstance(main_agent, agent_module.Assistant)
    assert main_agent.user_id == "caller-1"
    assert main_agent.chat_ctx.messages()[0].text_content == (
        "Actually government schemes ke baare mein batao."
    )
    assert handback_context.session.announcements == [
        "मैं आपको इसके लिए वापस main assistant से connect करती हूँ।"
    ]
    assert active_agents == ["connecting_main"]


def test_personal_finance_specialist_returns_to_main(monkeypatch) -> None:
    monkeypatch.setattr(agent_module.murf, "TTS", lambda **kwargs: SimpleNamespace())
    context = ChatContext.empty()
    context.add_message(role="user", content="Help me make a monthly budget.")
    context.add_message(
        role="user",
        content="I need help filing my ITR. I have Form 16 but do not understand it.",
    )
    active_agents: list[str] = []

    async def set_active_agent(agent_id: str) -> None:
        active_agents.append(agent_id)

    specialist = agent_module.PersonalFinanceSpecialist(
        context, user_id="caller-1", set_active_agent=set_active_agent
    )

    main_agent = asyncio.run(
        next(
            tool
            for tool in specialist.tools
            if tool._info.name == "return_to_main_agent"
        )._func(
            specialist,
            _context(
                "I need help filing my ITR. I have Form 16 but do not understand it."
            ),
        )
    )

    assert isinstance(main_agent, agent_module.Assistant)
    assert main_agent.user_id == "caller-1"
    assert main_agent.chat_ctx.messages()[-1].text_content == (
        "I need help filing my ITR. I have Form 16 but do not understand it."
    )
    assert active_agents == ["connecting_main"]
    assert (
        "you MUST call return_to_main_agent"
        in agent_module.PERSONAL_FINANCE_SPECIALIST_PROMPT
    )


def test_tax_handoff_failure_keeps_main_agent_active(monkeypatch) -> None:
    def fail_specialist(*args, **kwargs):
        raise RuntimeError("Murf unavailable")

    monkeypatch.setattr(agent_module, "TaxGSTSpecialist", fail_specialist)
    assistant = agent_module.Assistant(user_id="caller-1")

    result = asyncio.run(
        _tool(assistant, "handoff_to_tax_gst")._func(
            assistant, _context("I need help filing my ITR.")
        )
    )

    assert result["handoff"] == "failed"
    assert "couldn't connect you to the tax and GST specialist" in result["next_step"]


def test_handoff_context_omits_sensitive_credentials() -> None:
    context = ChatContext.empty()
    context.add_message(role="user", content="My account number is 1234567890123456.")

    safe_context = agent_module._safe_handoff_context(context)

    assert safe_context.messages()[0].text_content == (
        "[Sensitive details omitted from specialist handoff.]"
    )


def test_main_routing_keeps_schemes_and_budgeting_out_of_tax_gst() -> None:
    assert "Do not hand off government-scheme discovery" in agent_module.SYSTEM_PROMPT
    assert "personal budgeting, savings, expenses, and EMI/debt planning" in (
        agent_module.SYSTEM_PROMPT
    )
    assert "Respond in Devanagari" not in agent_module.TAX_GST_SPECIALIST_PROMPT
    assert "respond in Devanagari" in agent_module.TAX_GST_SPECIALIST_PROMPT


def test_handoff_announcements_select_exactly_one_language() -> None:
    assert agent_module._handoff_announcement(
        "tax_gst", "I need help filing my ITR."
    ) == (
        "I'll connect you with our tax and GST specialist who can guide you through this."
    )
    assert agent_module._handoff_announcement(
        "personal_finance", "Meri salary 30000 hai, budget bana do."
    ) == (
        "मैं आपको हमारे personal finance specialist से connect करती हूँ, जो आपका "
        "practical budget बनाने में मदद करेंगे।"
    )
