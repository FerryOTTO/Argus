"""Test chat WebSocket end-to-end"""
import asyncio, json, sys, urllib.request

# 1. Login via HTTP
import urllib.request as _req
body = json.dumps({"username":"alice","password":"test12345"}).encode()
req = _req.Request("http://127.0.0.1:3000/auth/login", data=body,
                    headers={"Content-Type":"application/json"})
resp = json.loads(_req.urlopen(req).read())
token = resp["access_token"]
print(f"Token: {token[:50]}...")

# 2. Chat WebSocket
async def chat():
    import websockets
    ws_url = f"ws://127.0.0.1:3000/chat?token={token}"
    print(f"Connecting: {ws_url}")
    async with websockets.connect(ws_url) as ws:
        print("Connected!")
        print("Sending: hello, just say hi")
        await ws.send("hello, just say hi and nothing else")

        # Collect all deltas
        full = ""
        try:
            while True:
                chunk = await asyncio.wait_for(ws.recv(), timeout=25)
                full += chunk
                sys.stdout.write(chunk)
                sys.stdout.flush()
        except asyncio.TimeoutError:
            pass

        if full.strip():
            print(f"\n\nTotal reply: {len(full)} chars")
        else:
            print("\n\nNO REPLY - chat flow broken")

asyncio.run(chat())
