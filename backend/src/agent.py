import logging
import re
from typing import Any

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    RunContext,
    cli,
    function_tool,
    room_io,
    tokenize,
)
from livekit.plugins import deepgram, google, murf, noise_cancellation, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from financial_schemes import discover_financial_schemes
from memory import delete_user, get_user, init_db, upsert_user
from memory_api import start_in_background

logger = logging.getLogger("agent")

load_dotenv(".env.local")

# Change this prompt to change what your voice agent does.
# See README.md for example prompts (customer support, language tutor, receptionist).
SYSTEM_PROMPT = """
You are Bharat Finance Assistant.

You are a friendly multilingual AI voice assistant.

You can help with:
- Budget planning
- Saving money
- Basic investment concepts
- UPI and digital payments
- Banking terminology
- Credit scores
- Insurance basics
- Financial literacy

Rules:
- Speak in a warm, conversational tone.
- Keep responses short and easy to understand.
- If asked for financial advice, provide educational guidance instead of making investment decisions.
- If you don't know something, honestly say so.
-You are patient, polite, and speak naturally.
-You are NOT a bank employee.



GREETING

At the beginning of every new call, first use the lookup_user tool to check
whether you already have saved information about the caller.

If no saved memory exists:
- Give a short, warm first-time greeting.
- Do not claim to know the caller.

If saved memory exists:
- Greet the caller by their saved name.
- Welcome them back naturally.
- If there is a relevant saved fact, briefly reference it.
- Do not repeat or list all saved memories.
- Do not use the generic first-time greeting for a returning caller.

Examples:

New caller:
"Namaste! Welcome to Bharat Finance Assistant. I'm here to help you with banking, UPI, loans, savings, and financial safety. How can I help you today?"

Returning caller:
"Namaste Ramesh, welcome back! Last time we talked about government savings schemes. Would you like to continue with that?"

Keep the greeting brief and conversational.


OBJECTIVES

1. Help users understand banking and UPI.
2. Explain government financial schemes.
3. Educate users about online banking safety.
4. Direct users to official bank support when necessary.


GUARDRAILS

Never:
- Ask for OTP
- Ask for PIN
- Ask for Password
- Ask for CVV
- Ask for debit or credit card details

Never claim:
- A loan is approved
- A payment is complete
- You can access bank accounts
- You work for a bank

If a user requests account-specific help, politely refuse and direct them to the official bank support.


LANGUAGE & SCRIPT

Always respond in the language the user is currently speaking.

The most recent user message determines the response language.

If the user switches language during the conversation, immediately switch the
response language to match the user's new language.

Hindi handling:

If the user's message is Hindi, treat it as Hindi even when the user speaks
or the transcript contains Romanized Hindi.

Romanized Hindi is only an input/transcription format. It does NOT mean that
the response should be written in Roman/Latin characters.

When responding in Hindi, generate the Hindi portions in Devanagari script.

Examples:

User:
"Mujhe government schemes ke baare mein batao."

Assistant:
"मुझे सरकारी योजनाओं के बारे में बताइए।"

User:
"Main kin schemes ke liye eligible hoon?"

Assistant:
"मैं किन योजनाओं के लिए eligible हूँ?"

If the user's message is English, respond in English.

If the user switches from Hindi to English, immediately respond in English.
If the user switches from English to Hindi, immediately respond in Hindi.

Do not create a separate Hinglish response category.

English:
- If the user speaks English, respond in English.

Do NOT create a separate Hinglish language category.

For this assistant, Romanized Hindi is treated as Hindi, even when the
transcript uses Latin/Roman characters.

Examples:

User:
"Mere liye kaunsi government schemes available hain?"
Assistant:
Respond in Hindi.

User:
"Main kin schemes ke liye eligible hoon?"
Assistant:
Respond in Hindi.

User:
"मुझे सरकारी योजनाओं के बारे में बताओ।"
Assistant:
Respond in Hindi.

User:
"I want to know about government schemes."
Assistant:
Respond in English.

User:
"Which schemes am I eligible for?"
Assistant:
Respond in English.

Language switching examples:

If the assistant is currently speaking Hindi and the user says:
"I want to know about education schemes."
→ Respond in English.

If the assistant is currently speaking English and the user says:
"Mujhe education schemes ke baare mein batao."
→ Respond in Hindi.

If the user switches back to English:
"Which ones am I eligible for?"
→ Respond in English.

The previous assistant response language must never override the language of
the latest user message.

Do not infer the response language from the conversation as a whole.
Determine it from the user's current/latest message.


MEMORY
- Use lookup_user at the beginning of a conversation and when the caller asks what you remember.
- If memory is found, welcome the caller back by name when available and mention at most one relevant fact.
- Never claim to remember anything not returned by lookup_user.
- Before save_user, ask for clear, explicit permission to save the specific safe information. Vague responses are not consent.
- If the caller says no, do not call save_user. Never save account numbers, government IDs, OTPs, PINs, passwords, CVVs, or card details.
- If a caller asks to forget everything, confirm deletion unless the request is already an unambiguous instruction to delete all memories.

GOVERNMENT SCHEMES
- Use find_financial_schemes for current Indian government financial or welfare scheme discovery, including state-specific availability.
- When the caller asks which discovered schemes they are eligible for, call find_financial_schemes with check_eligibility=true. This performs a fresh official-criteria search and compares only saved, non-sensitive facts.
- If the tool returns needs_more_information, ask only for its missing_information fields; do not ask again for facts already returned from memory. Never automatically save the answer.
- If it returns needs_official_verification, say the official extract was insufficient; do not infer eligibility from a scheme name or broad category.
- Do not use that tool for general budgeting, investments, UPI, or banking explanations.
- Before summarising results, clearly distinguish official-source information from a preliminary eligibility inference. Never promise eligibility; say official verification is required.
- Speak only a brief summary, never raw tool data. Mention that results were retrieved today (or the source update date if supplied).

"""

SENSITIVE_MEMORY_PATTERN = re.compile(
    r"\b(otp|pin|password|cvv|account\s*(number|no)?|card\s*(number|details)?|aadhaar|pan\s*(number|no)?)\b",
    re.IGNORECASE,
)
# TEMPORARY_MULTILINGUAL_DIAGNOSTICS: remove after the reproduction is captured.
DIAGNOSTIC_NUMBER_PATTERN = re.compile(r"\b\d{6,19}\b")


def _diagnostic_text(text: str | None) -> str:
    """Keep temporary pipeline logs useful without writing financial credentials."""
    value = (text or "").strip()
    if SENSITIVE_MEMORY_PATTERN.search(value) or DIAGNOSTIC_NUMBER_PATTERN.search(
        value
    ):
        return "[REDACTED: potentially sensitive content]"
    return value


def _install_pipeline_diagnostics(session: AgentSession) -> None:
    """TEMPORARY_MULTILINGUAL_DIAGNOSTICS for one reproduction call."""

    def on_user_input_transcribed(event: Any) -> None:
        if event.is_final:
            logger.info(
                "[DEBUG-STT] final transcript=%r language=%s",
                _diagnostic_text(event.transcript),
                event.language,
            )

    def on_conversation_item_added(event: Any) -> None:
        item = event.item
        if getattr(item, "role", None) == "assistant":
            logger.info(
                "[DEBUG-LLM] assistant text committed after playout=%r",
                _diagnostic_text(getattr(item, "text_content", None)),
            )

    def on_metrics_collected(event: Any) -> None:
        metrics = event.metrics
        metric_type = getattr(metrics, "type", "unknown")
        if metric_type in {"stt_metrics", "llm_metrics", "tts_metrics"}:
            logger.info(
                "[DEBUG-%s] metrics=%s", metric_type.split("_")[0].upper(), metrics
            )

    def on_error(event: Any) -> None:
        logger.error(
            "[DEBUG-%s] pipeline error: %s",
            type(event.source).__name__.upper(),
            event.error,
        )

    session.on("user_input_transcribed", on_user_input_transcribed)
    session.on("conversation_item_added", on_conversation_item_added)
    session.on("metrics_collected", on_metrics_collected)
    session.on("error", on_error)


class Assistant(Agent):
    def __init__(self, user_id: str | None = None) -> None:
        super().__init__(instructions=SYSTEM_PROMPT)
        self.user_id = user_id
        self._last_scheme_candidates: list[dict[str, str]] = []

    def _require_user_id(self) -> str:
        if not self.user_id:
            raise ValueError("Caller identity is unavailable for this session.")
        return self.user_id

    @function_tool
    async def lookup_user(self, context: RunContext) -> dict[str, Any]:
        """Retrieve the current caller's saved memory without asking for an ID."""
        user = get_user(self._require_user_id())
        if user is None:
            return {"found": False}
        return {
            "found": True,
            "name": user["name"],
            "language_preference": user["language_preference"],
            "facts": user["facts"],
        }

    @function_tool
    async def save_user(
        self,
        context: RunContext,
        name: str | None = None,
        language_preference: str | None = None,
        facts: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Save only explicitly consented, non-sensitive information for this caller."""
        values = [
            name or "",
            language_preference or "",
            *(facts or {}).keys(),
            *(facts or {}).values(),
        ]
        if any(SENSITIVE_MEMORY_PATTERN.search(value) for value in values):
            return {"saved": "false", "reason": "Sensitive data cannot be saved."}
        safe_facts = {
            key.strip(): value.strip()
            for key, value in (facts or {}).items()
            if key.strip() and value.strip()
        }
        upsert_user(
            self._require_user_id(),
            name=name.strip() if name else None,
            language_preference=language_preference.strip()
            if language_preference
            else None,
            facts=safe_facts,
        )
        return {"saved": "true"}

    @function_tool
    async def forget_user(self, context: RunContext) -> dict[str, str]:
        """Delete all saved memory for the current caller after clear confirmation."""
        return {"deleted": "true" if delete_user(self._require_user_id()) else "false"}

    @function_tool
    async def find_financial_schemes(
        self,
        context: RunContext,
        state: str | None = None,
        user_need: str | None = None,
        check_eligibility: bool = False,
    ) -> dict[str, Any]:
        """Find current Indian government financial or welfare schemes from official sources.

        Use this when a caller asks which government schemes may be available to them,
        asks about nationwide or Indian-state-specific schemes. Set `check_eligibility`
        to true only when the caller asks whether they qualify for schemes already
        discussed or found; it then retrieves official eligibility criteria and compares
        them with saved, non-sensitive facts. Do not use it for generic budgeting,
        investing, UPI, or banking questions. `state` is the Indian state the caller
        asked about, if any; `user_need` is a short non-sensitive need or profile detail
        that would improve the search, if given.
        """
        user = get_user(self.user_id) if self.user_id else None
        facts = user.get("facts", {}) if user else {}
        remembered_state = facts.get("state") or facts.get("State")
        result = await discover_financial_schemes(
            state=state or remembered_state,
            user_need=user_need,
            facts=facts,
            check_eligibility=check_eligibility,
            scheme_candidates=(
                self._last_scheme_candidates if check_eligibility else None
            ),
        )
        if not check_eligibility:
            self._last_scheme_candidates = result.get("scheme_candidates", [])
        return result

    # To add tools, use the @function_tool decorator.
    # Here's an example that adds a simple weather tool.
    # You also have to add `from livekit.agents import function_tool, RunContext` to the top of this file
    # @function_tool
    # async def lookup_weather(self, context: RunContext, location: str):
    #     """Use this tool to look up current weather information in the given location.
    #
    #     If the location is not supported by the weather service, the tool will indicate this. You must tell the user the location's weather is unavailable.
    #
    #     Args:
    #         location: The location to look up weather information for (e.g. city name)
    #     """
    #
    #     logger.info(f"Looking up weather for {location}")
    #
    #     return "sunny with a temperature of 70 degrees."


server = AgentServer()


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


def caller_identity(ctx: JobContext) -> str | None:
    participants = list(ctx.room.remote_participants.values())
    return participants[0].identity if participants else None


@server.rtc_session(agent_name="my-agent")
async def my_agent(ctx: JobContext):
    # Logging setup
    # Add any other context you want in all log entries here
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }
    init_db()
    await ctx.connect()

    # Set up a voice AI pipeline using Murf Falcon, Gemini, Deepgram, and the LiveKit turn detector
    session = AgentSession(
        # Speech-to-text (STT) is your agent's ears, turning the user's speech into text that the LLM can understand
        # See all available models at https://docs.livekit.io/agents/models/stt/
        stt=deepgram.STT(
            model="nova-3",
            language="multi",
        ),
        # A Large Language Model (LLM) is your agent's brain, processing user input and generating a response
        # See all available models at https://docs.livekit.io/agents/models/llm/
        llm=google.LLM(
            model="gemini-3.5-flash-lite",
        ),
        # Text-to-speech (TTS) is your agent's voice, turning the LLM's text into speech that the user can hear
        # See all available models as well as voice selections at https://docs.livekit.io/agents/models/tts/
        tts=murf.TTS(
            voice="Anisha",
            style="Conversation",
            tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=2),
            text_pacing=True,
        ),
        # VAD and turn detection are used to determine when the user is speaking and when the agent should respond
        # See more at https://docs.livekit.io/agents/build/turns
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        # allow the LLM to generate a response while waiting for the end of turn
        # See more at https://docs.livekit.io/agents/build/audio/#preemptive-generation
        preemptive_generation=True,
    )
    _install_pipeline_diagnostics(session)

    # To use a realtime model instead of a voice pipeline, use the following session setup instead.
    # (Note: This is for the OpenAI Realtime API. For other providers, see https://docs.livekit.io/agents/models/realtime/))
    # 1. Install livekit-agents[openai]
    # 2. Set OPENAI_API_KEY in .env.local
    # 3. Add `from livekit.plugins import openai` to the top of this file
    # 4. Use the following session setup instead of the version above
    # session = AgentSession(
    #     llm=openai.realtime.RealtimeModel(voice="marin")
    # )

    # # Add a virtual avatar to the session, if desired
    # # For other providers, see https://docs.livekit.io/agents/models/avatar/
    # avatar = hedra.AvatarSession(
    #   avatar_id="...",  # See https://docs.livekit.io/agents/models/avatar/plugins/hedra
    # )
    # # Start the avatar and wait for it to join
    # await avatar.start(session, room=ctx.room)

    # Start the session, which initializes the voice pipeline and warms up the models
    await session.start(
        agent=Assistant(caller_identity(ctx)),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: (
                    noise_cancellation.BVCTelephony()
                    if params.participant.kind
                    == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                    else noise_cancellation.BVC()
                ),
            ),
        ),
    )


if __name__ == "__main__":
    start_in_background()
    cli.run_app(server)
