import os
from dotenv import load_dotenv

from livekit.agents import (
    AgentSession,
    JobContext
)
from livekit.plugins import (
    silero,
    deepgram,
    cartesia,
)
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from langchain_community.chat_models import ChatOpenAI
dotenv_path = os.getenv("DOTENV_PATH", ".env")
print("Dotenv path :", dotenv_path)
load_dotenv(dotenv_path)

# ✅ General-purpose LangChain wrapper
class LangChainAgentWrapper:
    def __init__(self, model: str = None, temperature: float = 0.3, tools: list = None):
        self.model = model or "gpt-4o-mini" 
        self.temperature = temperature
        self.tools = tools or []

        self.llm = ChatOpenAI(
            model_name=self.model,
            temperature=self.temperature
        )

    def run(self, prompt: str):
        return self.llm.invoke(prompt)

def common_agent_session(ctx: JobContext, participant, llm_instance):
    session = AgentSession(
        userdata={
            "api": ctx.api,
            "participant": participant,
            "room": ctx.room,
        },
        vad=silero.VAD.load(activation_threshold=0.6),
        stt=deepgram.STT(model='enhanced-phonecall'),
        llm=llm_instance,
        tts=cartesia.TTS(model='sonic', speed='normal'),
        turn_detection=MultilingualModel(),
    )
    return session 