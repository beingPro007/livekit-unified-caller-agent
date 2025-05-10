# LiveKit Outbound Caller Voice Agent

A basic example of a voice agent using LiveKit and Python. Has a few extras to get started:

## Dev Setup

Run the following commands to:
- clone the repository
- change directory to `livekit-outbound-caller-agent`
- create a virtual environment and activate it
- install dependencies
- download files

### Linux/macOS
```console
git clone https://github.com/kylecampbell/livekit-outbound-caller-agent.git
cd livekit-outbound-caller-agent
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 agent.py download-files
```

<details>
  <summary>Windows instructions (click to expand)</summary>
  
```cmd
:: Windows (CMD/PowerShell)
cd livekit-outbound-caller-agent
python3 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```
</details>


Set up the environment by copying `.env.example` to `.env.local` and filling in the required values:

- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`
- `OPENAI_API_KEY`
- `DEEPGRAM_API_KEY`
- `SIP_OUTBOUND_TRUNK_ID` (obtained from directions below)

You can also do this automatically using the LiveKit CLI:

```console
lk app env
```

Run the agent:

```console
python3 agent.py dev
```

Now, your worker is running, and waiting for dispatches in order to make outbound calls.

## Create Twilio SIP Outbound Trunk
1. Create a Twilio account
2. Get a Twilio phone number
3. Create a SIP trunk
- In Twilio console go to Explore products > Elastic SIP Trunking > SIP Trunks > Get started > Create a SIP Trunk, name it, then Save.
4. Configure SIP Termination
- Go to Termination, enter a Termination SIP URI, select the plus icon for Credentials Lists, enter a friendly name, username, and password.

## Create LiveKit SIP Outbound Trunk
1. Using the outbound-trunk-example.json file, copy and rename to outbound-trunk.json and update it with your SIP provider's credentials. Do not push this file to a public repo.
- `name`: Can be anything
- `address`: Your SIP provider's outbound trunk address you created in previous step `Termination SIP URI`
- `numbers`: Your Twilio phone number you want to call from
- `auth_username`: Your username created in previous step in Twilio console.
- `auth_password`: Your password created in previous step in Twilio console.
2. Run LiveKit CLI command to create the trunk:
```console
lk sip outbound create outbound-trunk.json
```
3. Copy the `SIPTrunkID` returned in the response and add it to the `.env.local` file as `SIP_OUTBOUND_TRUNK_ID`.

You should now be able to make a call by dispatching an agent...

## Making a call
Open a new terminal while your agent is running. You can dispatch the agent to make a call by using the lk CLI (replace with number you want to call):

```console
lk dispatch create \
  --new-room \
  --agent-name outbound-caller \
  --metadata '+1234567890'
```

### Helpful commands

```console
lk project list
```

```console
lk sip outbound list
```

```console
lk sip dispatch list
```

