# agent_server.py

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import subprocess
import json
import uvicorn
import os

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

AGENT_NAME = "unified-caller"

class CallRequest(BaseModel):
    room: str
    phone_number: str


import os
import sys

@app.post("/start_call")
async def start_call(req: CallRequest):
    if os.getenv("RUN_MAIN") and os.getenv("RUN_MAIN") != "true":
        # Skip subprocess call in the extra reload process
        return {"message": "Skipping due to reload process"}

    print(f"Dispatch triggered with room: {req.room}, phone: {req.phone_number}")
    
    metadata = {
        "phone_number": req.phone_number
    }

    metadata_json = json.dumps(metadata)
    try:
        cmd = [
            "lk", "dispatch", "create",
            "--room", req.room,
            "--agent-name", AGENT_NAME,
            "--metadata", metadata_json
        ]
        
        env = os.environ.copy()
        env["LIVEKIT_URL"] = "wss://duply-talk-r93j68n8.livekit.cloud"
        env["api_key"] = "APIgj9v7rGTtPhk"
        
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)

        if result.returncode != 0:
            raise Exception(result.stderr)

        return {"message": "Call dispatched successfully", "output": result.stdout}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Dispatch failed: {str(e)}")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

