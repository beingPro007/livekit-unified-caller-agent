# agent_server.py

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import subprocess
import json
import uvicorn

app = FastAPI()

AGENT_NAME = "unified-caller"

class CallRequest(BaseModel):
    room: str
    phone_number: str


@app.post("/start_call")
async def start_call(req: CallRequest):
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
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise Exception(result.stderr)

        return {"message": "Call dispatched successfully", "output": result.stdout}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Dispatch failed: {str(e)}")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
