"""Outbound Linphone/SIP agent for the Financial Services assistant.

Run from ``backend`` with ``uv run python src/telephony/outbound/agent.py dev``.
The destination is supplied by ``dial.py`` in dispatch metadata.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import sys
from pathlib import Path
from types import ModuleType

from dotenv import load_dotenv
from livekit import api, rtc
from livekit.agents import (
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

# Direct-script execution (the documented command) does not put src/ on sys.path.
SRC_DIR = Path(__file__).resolve().parents[2]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from memory import get_user, init_db, upsert_user  # noqa: E402


def load_day5_agent_module() -> ModuleType:
    module_path = SRC_DIR / "agent.py"
    spec = importlib.util.spec_from_file_location("day5_financial_agent", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load Day 5 agent module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


Assistant = load_day5_agent_module().Assistant

logger = logging.getLogger("outbound-agent")
load_dotenv(".env.local")

OUTBOUND_TRUNK_ID = os.getenv("LIVEKIT_SIP_OUTBOUND_TRUNK_ID")
CALLEE_IDENTITY = "phone-user"

OUTBOUND_SCRIPT_INSTRUCTIONS = """
Outbound Hindi/Hinglish pronunciation rule:
- When speaking Hindi or Hinglish, write Hindi words only in Devanagari script.
- Keep common English terms in English/Latin script, such as government, scheme,
  eligible, application, deadline, stop, reminder, call, and assistant.
- Never transliterate Hindi words into Roman/Latin script.
- Speak naturally like an Indian Hindi-speaking caller.
- If the caller speaks fully in English, English sentences can remain fully English.
"""

LANGUAGE_SELECTION_INSTRUCTIONS = """
Outbound call language selection:
- The initial greeting asks whether the caller wants Hindi or English.
- Store the caller's choice for this call using set_call_language.
- If the caller says Hindi, हिंदी, Hindi mein baat karo, or similar, call
  set_call_language with "hindi" and continue in Hindi/Hinglish.
- If the caller says English, अंग्रेज़ी, English mein baat karo, or similar,
  call set_call_language with "english" and continue in natural English.
- If the caller's first answer is not a clear language choice, ask once:
  "आप हिंदी में बात करना चाहेंगे या English में?"
- Do not repeatedly ask for language.
- If the caller says stop at any time, use the opt_out tool.
"""

LANGUAGE_QUESTION = "आप हिंदी में बात करना चाहेंगे या English में?"

GREETING = (
    "नमस्ते, मैं Bharat Finance Assistant की automated financial assistance "
    "assistant बोल रही हूँ। आप जिस government scheme के लिए eligible हैं, "
    "उसकी application की deadline करीब आ रही है, इसलिए मैं आपको reminder "
    "देने के लिए call कर रही हूँ। अगर आप ऐसे calls नहीं लेना चाहते, तो "
    "'stop' कह सकते हैं। क्या आपके पास scheme के बारे में कोई सवाल है?"
)

MEMORY_FALLBACK_USER_ID = "anon_00000000-0000-4000-8000-000000000006"


class OutboundAgent(Assistant):
    """Reuse Day 5's tools and memory with outbound-call controls."""

    def __init__(self, ctx: JobContext, callee_id: str) -> None:
        super().__init__(callee_id)
        self.ctx = ctx
        self.call_language: str | None = None

    @function_tool
    async def set_call_language(self, context: RunContext, language: str) -> str:
        """Set this outbound call's language to Hindi or English."""
        normalized = language.strip().lower()
        if normalized not in {"hindi", "english"}:
            return "Ask once whether the caller wants Hindi or English."
        self.call_language = normalized
        if normalized == "english":
            await self.update_instructions(
                f"{self.instructions}\n\nCurrent call language: English. "
                "Continue naturally in English. Do not use Devanagari Hindi "
                "sentences unless the caller switches back to Hindi."
            )
            return "Continue the call in English."
        await self.update_instructions(
            f"{self.instructions}\n\nCurrent call language: Hindi. Continue in "
            "Hindi/Hinglish. Write Hindi words in Devanagari and keep common "
            "English service terms in Latin script where natural."
        )
        return "हिंदी/Hinglish में बातचीत जारी रखें।"

    @function_tool
    async def opt_out(self, context: RunContext) -> str:
        """Use when the caller says stop, remove me, or opts out of reminder calls."""
        user = get_user(self._require_user_id()) or {}
        name = user.get("name")
        upsert_user(
            self._require_user_id(),
            facts={
                "outbound_scheme_deadline_reminders": "opted_out",
                "opt_out_preference": "true",
            },
        )
        if self.call_language == "english":
            salutation = f"{name}, " if name else ""
            message = (
                f"Okay {salutation}I understand. You will not receive these "
                "reminder calls anymore."
            )
        else:
            salutation = f"{name} जी, " if name else ""
            message = (
                f"ठीक है {salutation}समझ गई। अब आपको ऐसी reminder calls नहीं आएँगी।"
            )
        await context.session.say(
            message,
            allow_interruptions=False,
        )
        await self._hangup()
        return "The caller opted out and the call was ended."

    @function_tool
    async def end_call(self, context: RunContext) -> str:
        """End the call after a polite goodbye."""
        await context.session.say("धन्यवाद। नमस्ते।", allow_interruptions=False)
        await self._hangup()
        return "Call ended."

    async def _hangup(self) -> None:
        await self.ctx.api.room.delete_room(api.DeleteRoomRequest(room=self.ctx.room.name))


server = AgentServer()


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


def phone_number_from_metadata(ctx: JobContext) -> str | None:
    metadata = outbound_metadata(ctx)
    if metadata:
        return metadata.get("phone_number")
    return ctx.job.metadata.strip() or None


def outbound_metadata(ctx: JobContext) -> dict[str, str]:
    if not ctx.job.metadata:
        return {}
    try:
        parsed = json.loads(ctx.job.metadata)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): str(value) for key, value in parsed.items() if value is not None}


def memory_user_id_from_metadata(ctx: JobContext) -> str:
    return outbound_metadata(ctx).get("user_id") or MEMORY_FALLBACK_USER_ID


def build_memory_greeting(user: dict | None) -> str:
    if not user:
        return f"{GREETING} {LANGUAGE_QUESTION}"
    facts = user.get("facts", {})
    name = user.get("name")
    scheme = facts.get("eligible_scheme")
    eligibility = facts.get("eligibility_status")
    reminder_reason = facts.get("reminder_reason")
    if name and scheme and eligibility:
        reason_line = (
            "इसकी deadline करीब आ रही है"
            if reminder_reason
            else "मैं आपको इसी के बारे में बताने के लिए call कर रही हूँ"
        )
        return (
            f"नमस्ते {name} जी। आप {scheme} scheme के लिए {eligibility} हैं और "
            f"{reason_line}। मैं आपको इसी के बारे में reminder देने के लिए call "
            "कर रही हूँ। अगर आप ऐसे calls नहीं लेना चाहते, तो 'stop' कह सकते हैं। "
            f"{LANGUAGE_QUESTION}"
        )
    return f"{GREETING} {LANGUAGE_QUESTION}"


def build_memory_instruction(user: dict | None) -> str:
    if not user:
        return ""
    facts = user.get("facts", {})
    name = user.get("name")
    scheme = facts.get("eligible_scheme")
    eligibility = facts.get("eligibility_status")
    exact_deadline = facts.get("exact_deadline")
    reminder_reason = facts.get("reminder_reason")
    opt_out = facts.get("opt_out_preference")
    return f"""
Saved outbound reminder memory retrieved at runtime:
- name: {name or "unknown"}
- eligible_scheme: {scheme or "unknown"}
- eligibility_status: {eligibility or "unknown"}
- reminder_reason: {reminder_reason or "unknown"}
- exact_deadline: {exact_deadline or "not available"}
- opt_out_preference: {opt_out or "false"}

Use this persisted memory naturally during the outbound call.
If asked which scheme this call is about, answer using eligible_scheme from memory.
If asked about the exact deadline and exact_deadline is "not available", say you
cannot confirm the exact deadline and the caller should check the official portal.
Do not invent a date.
If the caller says stop, use the opt_out tool.
"""


def log_participant_tracks(participant: rtc.RemoteParticipant) -> None:
    logger.info(
        "[OUTBOUND-DEBUG] participant=%s kind=%s track_publications=%s",
        participant.identity,
        rtc.ParticipantKind.Name(participant.kind),
        [
            {
                "sid": publication.sid,
                "kind": rtc.TrackKind.Name(publication.kind),
                "source": rtc.TrackSource.Name(publication.source),
                "subscribed": publication.subscribed,
                "has_track": publication.track is not None,
            }
            for publication in participant.track_publications.values()
        ],
    )


def install_room_debug_logging(ctx: JobContext) -> None:
    def on_participant_connected(participant: rtc.RemoteParticipant) -> None:
        logger.info(
            "[OUTBOUND-DEBUG] participant joined identity=%s kind=%s",
            participant.identity,
            rtc.ParticipantKind.Name(participant.kind),
        )
        log_participant_tracks(participant)

    def on_track_published(
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        logger.info(
            "[OUTBOUND-DEBUG] track published participant=%s sid=%s kind=%s "
            "source=%s subscribed=%s",
            participant.identity,
            publication.sid,
            rtc.TrackKind.Name(publication.kind),
            rtc.TrackSource.Name(publication.source),
            publication.subscribed,
        )

    def on_track_subscribed(
        track: rtc.RemoteTrack,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        logger.info(
            "[OUTBOUND-DEBUG] track subscribed participant=%s sid=%s kind=%s "
            "source=%s track_sid=%s",
            participant.identity,
            publication.sid,
            rtc.TrackKind.Name(publication.kind),
            rtc.TrackSource.Name(publication.source),
            track.sid,
        )

    ctx.room.on("participant_connected", on_participant_connected)
    ctx.room.on("track_published", on_track_published)
    ctx.room.on("track_subscribed", on_track_subscribed)


def install_session_debug_logging(session: AgentSession) -> asyncio.Event:
    session_closed = asyncio.Event()

    def on_user_input_transcribed(event) -> None:
        logger.info(
            "[OUTBOUND-DEBUG] STT transcript final=%s language=%s text=%r",
            event.is_final,
            event.language,
            event.transcript,
        )

    def on_conversation_item_added(event) -> None:
        item = event.item
        logger.info(
            "[OUTBOUND-DEBUG] conversation item role=%s text=%r",
            getattr(item, "role", None),
            getattr(item, "text_content", None),
        )

    def on_speech_created(event) -> None:
        logger.info(
            "[OUTBOUND-DEBUG] speech created source=%s user_initiated=%s",
            event.source,
            event.user_initiated,
        )

    def on_function_tools_executed(event) -> None:
        logger.info(
            "[OUTBOUND-DEBUG] tools executed calls=%s",
            [call.name for call in event.function_calls],
        )

    def on_metrics_collected(event) -> None:
        metrics = event.metrics
        logger.info(
            "[OUTBOUND-DEBUG] metrics type=%s data=%s",
            getattr(metrics, "type", type(metrics).__name__),
            metrics,
        )

    def on_error(event) -> None:
        logger.exception(
            "[OUTBOUND-DEBUG] session error source=%s error=%s",
            type(event.source).__name__,
            event.error,
        )

    def on_close(event) -> None:
        logger.warning(
            "[OUTBOUND-DEBUG] session closed reason=%s error=%s",
            event.reason,
            event.error,
        )
        session_closed.set()

    session.on("user_input_transcribed", on_user_input_transcribed)
    session.on("conversation_item_added", on_conversation_item_added)
    session.on("speech_created", on_speech_created)
    session.on("function_tools_executed", on_function_tools_executed)
    session.on("metrics_collected", on_metrics_collected)
    session.on("error", on_error)
    session.on("close", on_close)
    return session_closed


@server.rtc_session(agent_name="outbound-agent")
async def outbound_agent(ctx: JobContext) -> None:
    phone_number = phone_number_from_metadata(ctx)
    memory_user_id = memory_user_id_from_metadata(ctx)
    if not phone_number:
        logger.error("No phone number in dispatch metadata")
        ctx.shutdown()
        return
    if not OUTBOUND_TRUNK_ID:
        logger.error("LIVEKIT_SIP_OUTBOUND_TRUNK_ID is not set; cannot place calls")
        ctx.shutdown()
        return

    init_db()
    saved_user = get_user(memory_user_id)
    logger.info(
        "[OUTBOUND-DEBUG] memory lookup user_id=%s found=%s facts=%s",
        memory_user_id,
        saved_user is not None,
        sorted((saved_user or {}).get("facts", {}).keys()),
    )

    call_finished = asyncio.Event()
    linked_sip_identity = {"value": CALLEE_IDENTITY}

    def on_participant_disconnected(participant: rtc.RemoteParticipant) -> None:
        logger.info(
            "[OUTBOUND-DEBUG] participant disconnected identity=%s reason=%s",
            participant.identity,
            rtc.DisconnectReason.Name(
                participant.disconnect_reason or rtc.DisconnectReason.UNKNOWN_REASON
            ),
        )
        if participant.identity == linked_sip_identity["value"]:
            call_finished.set()

    await ctx.connect()
    install_room_debug_logging(ctx)
    ctx.room.on("participant_disconnected", on_participant_disconnected)
    try:
        sip_participant = await ctx.api.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=ctx.room.name,
                sip_trunk_id=OUTBOUND_TRUNK_ID,
                sip_call_to=phone_number,
                participant_identity=CALLEE_IDENTITY,
                participant_name="Phone user",
                wait_until_answered=True,
            )
        )
    except api.TwirpError as error:
        logger.error("Call to %s was not answered: %s", phone_number, error.message)
        ctx.shutdown()
        return
    sip_identity = sip_participant.participant_identity or CALLEE_IDENTITY
    linked_sip_identity["value"] = sip_identity
    logger.info(
        "[OUTBOUND-DEBUG] SIP participant API returned identity=%s id=%s room=%s call_id=%s",
        sip_identity,
        sip_participant.participant_id,
        sip_participant.room_name,
        sip_participant.sip_call_id,
    )
    if sip_identity != CALLEE_IDENTITY:
        logger.warning(
            "[OUTBOUND-DEBUG] SIP identity differs from requested identity: "
            "requested=%s actual=%s",
            CALLEE_IDENTITY,
            sip_identity,
        )

    sip_room_participant = await ctx.wait_for_participant(
        identity=sip_identity,
        kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
    )
    log_participant_tracks(sip_room_participant)
    session = AgentSession(
        stt=deepgram.STT(model="nova-3", language="multi"),
        llm=google.LLM(model="gemini-3.5-flash-lite"),
        tts=murf.TTS(
            voice="Anisha",
            style="Conversation",
            tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=2),
            text_pacing=True,
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )
    session_closed = install_session_debug_logging(session)
    outbound_assistant = OutboundAgent(ctx, memory_user_id)
    await session.start(
        agent=outbound_assistant,
        room=ctx.room,
        room_options=room_io.RoomOptions(
            participant_identity=sip_identity,
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: (
                    noise_cancellation.BVCTelephony()
                    if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                    else noise_cancellation.BVC()
                )
            ),
        ),
    )
    await outbound_assistant.update_instructions(
        f"{outbound_assistant.instructions}\n\n{OUTBOUND_SCRIPT_INSTRUCTIONS}"
        f"\n\n{LANGUAGE_SELECTION_INSTRUCTIONS}"
        f"\n\n{build_memory_instruction(saved_user)}"
    )
    await session.say(build_memory_greeting(saved_user), allow_interruptions=True)
    wait_tasks = {
        asyncio.create_task(call_finished.wait()),
        asyncio.create_task(session_closed.wait()),
    }
    _, pending = await asyncio.wait(
        wait_tasks,
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()


if __name__ == "__main__":
    cli.run_app(server)
