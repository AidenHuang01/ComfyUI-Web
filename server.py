from flask import Flask, request, send_file, jsonify, render_template_string
from flask_sock import Sock
import requests
import json
import time
import os
import websocket
import threading
import queue

app = Flask(__name__)
sock = Sock(app)

COMFY_API = "http://127.0.0.1:8188"  # ComfyUI server
COMFY_WS = "ws://127.0.0.1:8188/ws"  # ComfyUI WebSocket
OUTPUT_DIR = r"C:\baidu\full\ComfyUI_Wan22_Ultra_GGUF(full)\ComfyUI\output"  # ComfyUI output directory

# Queue to store WebSocket messages from ComfyUI
message_queue = queue.Queue()

def ws_comfyui_client():
    """Connect to ComfyUI WebSocket and forward messages to queue."""
    while True:
        try:
            ws = websocket.WebSocket()
            ws.connect(COMFY_WS)
            while True:
                message = ws.recv()
                message_queue.put(message)
        except Exception as e:
            print(f"ComfyUI WebSocket error: {e}, reconnecting...")
            time.sleep(1)

# Start ComfyUI WebSocket client in a separate thread
threading.Thread(target=ws_comfyui_client, daemon=True).start()

@app.route("/")
def index():
    with open("index.html") as f:
        return render_template_string(f.read())

@app.route("/generate", methods=["POST"])
def generate():
    try:
        data = request.json
        user_prompt = data.get("prompt", "")

        # Load fixed workflow
        with open("BasicT2I_API.json") as f:
            workflow = json.load(f)

        # Update the prompt in node 305
        node = workflow.get("305")
        if not node:
            return {"error": "Node 305 not found in workflow"}, 500
        node["inputs"]["wildcard_text"] = user_prompt
        node["inputs"]["populated_text"] = user_prompt

        # Send workflow to ComfyUI
        r = requests.post(f"{COMFY_API}/prompt", json={"prompt": workflow})
        if r.status_code != 200:
            return {"error": f"ComfyUI API error: {r.text}"}, r.status_code

        prompt_id = r.json().get("prompt_id")
        if not prompt_id:
            return {"error": "No prompt_id returned from ComfyUI"}, 500

        return jsonify({"prompt_id": prompt_id})

    except Exception as e:
        return {"error": f"Failed to generate image: {str(e)}"}, 500

@app.route("/get_image/<prompt_id>", methods=["GET"])
def get_image(prompt_id):
    try:
        print(f"Polling for image with prompt_id: {prompt_id}")
        # Poll for image output from node 400 (Image Saver)
        for attempt in range(300):  # Poll for 300 seconds
            history = requests.get(f"{COMFY_API}/history/{prompt_id}").json()
            outputs = history.get(prompt_id, {}).get("outputs", {})
            image_saver_output = outputs.get("400", {})
            if "images" in image_saver_output:
                file_name = image_saver_output["images"][0]["filename"]
                file_path = os.path.join(OUTPUT_DIR, file_name)
                print(f"Checking file: {file_path}")
                if os.path.exists(file_path):
                    print(f"Image found: {file_path}")
                    return send_file(file_path, mimetype="image/png")
                else:
                    print(f"Image not found: {file_path}")
            time.sleep(1)

        print(f"Timeout: No image found for prompt_id {prompt_id}")
        return {"error": "Timeout waiting for image from Image Saver node"}, 504

    except Exception as e:
        print(f"Error retrieving image for prompt_id {prompt_id}: {str(e)}")
        return {"error": f"Failed to retrieve image: {str(e)}"}, 500

@sock.route("/ws")
def websocket_route(ws):
    """Proxy WebSocket messages from ComfyUI to the client."""
    while True:
        try:
            message = message_queue.get_nowait()
            ws.send(message)
        except queue.Empty:
            time.sleep(0.1)
        except Exception as e:
            print(f"WebSocket proxy error: {e}")
            break

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)