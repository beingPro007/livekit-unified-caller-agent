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
        You are Phonio, the voice AI assistant on Phonio’s official website. You speak with visitors who want to learn about how Phonio works and how it can help their business. Phonio is an AI-powered voice automation platform that makes outbound phone calls to customers — handling tasks like order confirmations, reminders, feedback collection, lead follow-ups, and support callbacks. It integrates with platforms like Shopify and CRMs, and works across industries.
        Your job is to clearly and concisely explain what Phonio does, how it can be used, and what benefits it offers. Speak in a friendly, confident, and knowledgeable tone — like a helpful product expert. Keep responses short and easy to understand. Use simple language, avoid jargon, and don’t use punctuation that would be hard to pronounce. If a user asks something too technical or business-specific, guide them to book a demo or contact support.
        Always prioritize being helpful, engaging, and respectful of the user’s time. Your goal is to help them understand whether Phonio is a good fit for their business needs. 
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
        stt=deepgram.STT(model="nova-2-phonecall"),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=cartesia.TTS(),
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
        instructions=(
            "Greet the user, introduce yourself as Alexis from Gods of Growth, "
            "and ask how you can assist with their ecommerce business today. "
            "Keep it brief and clear."
        )
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
    data = await ctx.connect()
    logger.debug("Connected to room")
    logger.debug(f"Job metadata: {ctx.job.metadata}")

    # Normalize metadata
    raw_meta = ctx.job.metadata or ""
    if isinstance(raw_meta, str):
        if not raw_meta.strip():
            metadata = {}
        else:
            try:
                metadata = json.loads(raw_meta)
                logger.debug(f"Parsed metadata: {metadata}")
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}")
                raise ValueError(f"Could not parse metadata JSON: {raw_meta!r}")
    else:
        metadata = raw_meta

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

        logger.info(f"SIP call initiated from +1XXXXXXXXXX to {phone_number}")
        logger.debug("SIP participant created")
    except Exception as e:
        logger.error(f"Failed to create SIP participant: {e}")
        raise

    # Wait for SIP participant to join (no hangup or timeout anymore)
    try:
        participant = await ctx.wait_for_participant(identity=user_identity)
        logger.debug(f"SIP participant joined: {participant.identity}")
    except Exception as e:
        logger.error(f"Error waiting for SIP participant: {e}")
        raise

    # Monitor call status with a timeout and break early if still ringing after a period
    start_time = time.time()
    timeout = 30  # Timeout in seconds (you can adjust this value as needed)
    while True:
        status = participant.attributes.get("sip.callStatus")
        logger.debug(f"Call status: {status}")

        # If the call is active, user has picked up
        if status == "active":
            logger.info("User has picked up")
            break

        # If the call is rejected or terminated, stop the loop
        if status in ["terminated", "rejected"]:
            logger.info(f"Call was {status}, exiting the loop")
            break

        # If the call has been ringing for too long, break the loop
        if status == "ringing" and (time.time() - start_time) > timeout:
            logger.warning("Call is ringing too long, breaking the loop")
            break

        await asyncio.sleep(0.1)

    # Agent session
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
        instructions=f"Greet the user, introduce yourself as Phonio AI on behalf of Abhinav Baldha, and offer your assistance. Keep your response brief and clear."
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
