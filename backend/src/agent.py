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
    inference,
    tokenize,
    room_io,
)
from livekit.plugins import murf, silero, google, deepgram, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

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

If the user speaks entirely in English:
- Reply entirely in English.
- Use Latin/English script.
- Do not switch to Hindi unless the user switches to Hindi.

If the user speaks entirely in Hindi:
- Reply entirely in Hindi.
- Write Hindi in Devanagari script.
- Never write Hindi in Roman/Latin script.

If the user naturally mixes Hindi and English (Hinglish):
- Reply in the same mixed style.
- Write Hindi words in Devanagari.
- Write English words in Latin script.
- Do not romanize Hindi words.

If the user switches language during the conversation:
- Immediately switch the response language to match the user's new language.
- Do not continue using the previous language merely because it was used earlier.

Examples:

User: "What is UPI?"
Assistant: Reply entirely in English.

User: "यूपीआई क्या है?"
Assistant: Reply entirely in Hindi using Devanagari.

User: "UPI क्या है and how does it work?"
Assistant: Reply in natural mixed Hindi-English, with Hindi in Devanagari and English in Latin script.

MEMORY
- Use lookup_user at the beginning of a conversation and when the caller asks what you remember.
- If memory is found, welcome the caller back by name when available and mention at most one relevant fact.
- Never claim to remember anything not returned by lookup_user.
- Before save_user, ask for clear, explicit permission to save the specific safe information. Vague responses are not consent.
- If the caller says no, do not call save_user. Never save account numbers, government IDs, OTPs, PINs, passwords, CVVs, or card details.
- If a caller asks to forget everything, confirm deletion unless the request is already an unambiguous instruction to delete all memories.

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
    if SENSITIVE_MEMORY_PATTERN.search(value) or DIAGNOSTIC_NUMBER_PATTERN.search(value):
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
            logger.info("[DEBUG-%s] metrics=%s", metric_type.split("_")[0].upper(), metrics)

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
        values = [name or "", language_preference or "", *(facts or {}).keys(), *(facts or {}).values()]
        if any(SENSITIVE_MEMORY_PATTERN.search(value) for value in values):
            return {"saved": "false", "reason": "Sensitive data cannot be saved."}
        safe_facts = {key.strip(): value.strip() for key, value in (facts or {}).items() if key.strip() and value.strip()}
        upsert_user(
            self._require_user_id(),
            name=name.strip() if name else None,
            language_preference=language_preference.strip() if language_preference else None,
            facts=safe_facts,
        )
        return {"saved": "true"}

    @function_tool
    async def forget_user(self, context: RunContext) -> dict[str, str]:
        """Delete all saved memory for the current caller after clear confirmation."""
        return {"deleted": "true" if delete_user(self._require_user_id()) else "false"}

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
                text_pacing=True
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
