import asyncio
import logging
import json
import os
from dotenv import load_dotenv
import time

from livekit import rtc, api
from livekit.agents import (
    Agent,
    AgentSession,
    function_tool,
    RunContext,
    JobContext,
    WorkerOptions,
    cli,
    RoomInputOptions,
)
from livekit.plugins import deepgram, openai, silero, cartesia, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

logger = logging.getLogger("outbound-caller")
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler()
formatter = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

# Load environment
dotenv_path = os.getenv("DOTENV_PATH", ".env")
load_dotenv(dotenv_path=dotenv_path)
outbound_trunk_id = os.getenv("SIP_OUTBOUND_TRUNK_ID")
print(f"[DEBUG] Loaded SIP_OUTBOUND_TRUNK_ID = {outbound_trunk_id!r}")
if not outbound_trunk_id:
    raise RuntimeError("Missing SIP_OUTBOUND_TRUNK_ID from environment")

print("Outbound Trunk ID",outbound_trunk_id)
if not outbound_trunk_id or not outbound_trunk_id.startswith("ST_"):
    raise ValueError("SIP_OUTBOUND_TRUNK_ID is not set or invalid")

#This is the custom instruction which is being given to the AI agent on startup...
_default_instructions = (
    """
    You are Alexis, a helpful and knowledgeable voice assistant from Gods of Growth.
    Your role is to talk to potential clients about how Gods of Growth helps ecommerce brands
    grow their revenue using advanced marketing strategies and AI-powered solutions.

    Always sound friendly, clear, and engaging. Explain things simply and briefly.
    If someone wants more help, suggest they book a free strategy call through the website.

    Never use technical jargon, and don’t talk about Phonio or any other platform.
    """
)

# Inbound Calling agent

async def inbound_entrypoint(ctx: JobContext):
    logger.debug("inbound_entrypoint() called")

    # Join the dispatch-created room (no hard-coded name)
    await ctx.connect()
    logger.info(f"Agent connected to room: {ctx.room.name!r}")

    try:
        # Now wait for the SIP caller to join
        participant = await ctx.wait_for_participant()
        logger.info(f"Inbound call received from participant: {participant.identity}")
    except Exception as e:
        logger.error(f"Error waiting for inbound participant: {e}")
        raise

    # Start the AgentSession as before
    session = AgentSession(
        userdata={
            "api": ctx.api,
            "participant": participant,
            "room": ctx.room,
        },
        vad=silero.VAD.load(activation_threshold=0.6),
        stt=deepgram.STT(model='enhanced-phonecall'),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=cartesia.TTS(model='sonic', speed='normal'),
        turn_detection=MultilingualModel(),
    )

    logger.debug("Starting AgentSession (inbound)...")
    await session.start(
        room=ctx.room,
        agent=OutboundCallerAgent(),
        room_input_options=RoomInputOptions(noise_cancellation=noise_cancellation.BVC()),
    )

    logger.debug("Session started, sending greeting (inbound)...")
    await session.generate_reply(
        instructions="Hi there! This is Alexis calling from Gods of Growth. How can I help your ecommerce business today?"
    )

#Class for outbound Call agent
class OutboundCallerAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=_default_instructions)

    @function_tool()
    async def end_call(self, context: RunContext) -> None:
        logger.debug("end_call() function_tool invoked")
        api_client = context.userdata["api"]
        participant = context.userdata["participant"]
        room = context.userdata["room"]

        logger.info(f"Ending the call for {participant.identity}")
        try:
            await api_client.room.remove_participant(
                api.RoomParticipantIdentity(room=room.name, identity=participant.identity)
            )
            logger.debug("Participant removed successfully")
        except Exception as e:
            logger.error(f"Error ending call: {e}")

    @function_tool()
    async def look_up_availability(self, context: RunContext, date: str) -> dict:
        logger.info(f"Looking up availability on {date}")
        await asyncio.sleep(3)
        return {"available_times": ["1pm", "2pm", "3pm"]}

    @function_tool()
    async def confirm_appointment(self, context: RunContext, date: str, time: str) -> str:
        participant = context.userdata["participant"]
        logger.info(f"Confirming appointment for {participant.identity} on {date} at {time}")
        return "Reservation confirmed"

    @function_tool()
    async def detected_answering_machine(self, context: RunContext) -> None:
        logger.info("Detected answering machine")


async def outbound_entrypoint(ctx: JobContext):
    logger.debug("outbound_entrypoint() called")
    await ctx.connect()
    logger.debug("Connected to room")
    logger.debug(f"Job metadata: {ctx.job.metadata}")

    raw_meta = ctx.job.metadata or ""
    metadata = {}
    if isinstance(raw_meta, str) and raw_meta.strip():
        try:
            metadata = json.loads(raw_meta)
            logger.debug(f"Parsed metadata: {metadata}")
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            raise ValueError(f"Could not parse metadata JSON: {raw_meta!r}")

    phone_number = metadata.get("phone_number")
    if not phone_number:
        logger.error("Missing phone_number in job metadata")
        raise ValueError("Missing phone_number in job metadata")

    user_identity = "phone_user"
    logger.info(f"Dialing {phone_number} into room {ctx.room.name}")

    try:
        await ctx.api.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=ctx.room.name,
                sip_trunk_id=outbound_trunk_id,
                sip_call_to=phone_number,
                participant_identity=user_identity,
            )
        )
        logger.info(f"SIP call initiated to {phone_number}")
    except Exception as e:
        logger.error(f"Failed to create SIP participant: {e}")
        raise

    # Wait for SIP participant to join (with timeout + call status check)
    try:
        participant = await ctx.wait_for_participant(identity=user_identity)
        logger.debug(f"SIP participant joined: {participant.identity}")
    except Exception as e:
        logger.error(f"Error waiting for SIP participant: {e}")
        raise

    # Monitor call status
    start_time = time.time()
    timeout = 20  # seconds

    session_should_start = False

    while True:
        status = participant.attributes.get("sip.callStatus")

        if status == "active":
            session_should_start = True
            break

        if status in ["terminated", "rejected"]:
            break

        if status == "ringing" and (time.time() - start_time) > timeout:
            logger.warning("Call ringing too long, deleting room...")

            try:
                await ctx.api.room.delete_room(
                    api.DeleteRoomRequest(room=ctx.room.name)
                )
                logger.info("Room deleted successfully")
            except Exception as e:
                logger.error(f"Failed to delete room: {e}")

            return  # Exit early — do NOT start AgentSession

        await asyncio.sleep(0.1)
    # Only start session if user picked up
    if not session_should_start:
        logger.info("User did not pick up, skipping AgentSession")
        return

    session = AgentSession(
        userdata={
            "api": ctx.api,
            "participant": participant,
            "room": ctx.room,
        },
        vad=silero.VAD.load(activation_threshold=0.6),
        stt=deepgram.STT(model="nova-2-phonecall"),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=cartesia.TTS(),
        turn_detection=MultilingualModel(),
    )

    logger.debug("Starting AgentSession...")
    await session.start(
        room=ctx.room,
        agent=OutboundCallerAgent(),
        room_input_options=RoomInputOptions(noise_cancellation=noise_cancellation.BVC()),
    )

    logger.debug("Session started, sending greeting...")
    await session.generate_reply(
        instructions="Hi! I'm Alexis from Gods of Growth. How can I assist you with growing your ecommerce brand today?"
    )

async def unified_entrypoint(ctx: JobContext):
    logger.debug("unified_entrypoint() called")
    metadata = ctx.job.metadata or "{}"
    try:
        metadata_dict = json.loads(metadata)
    except Exception:
        metadata_dict = {}

    if "phone_number" in metadata_dict:
        logger.info("Detected outbound call (phone_number present)")
        await outbound_entrypoint(ctx)  # Calls your outbound logic
    else:
        logger.info("Detected inbound call (no phone_number)")
        await inbound_entrypoint(ctx)  # Calls your inbound logic

if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=unified_entrypoint,
            agent_name="unified-caller",
        )
    )
