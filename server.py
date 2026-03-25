import os
import io
import json
import uuid
import base64
import tempfile
import urllib.request
import urllib.parse
import logging
import websocket
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)

app = Flask(__name__)

COMFYUI_ADDRESS = "127.0.0.1:8000"
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKFLOW_PATH = os.path.join(OUTPUT_DIR, "sight_engine_bypasser_v2_api2.json")


def upload_image_to_comfyui(image_path, filename):
    """Upload an image to ComfyUI's input folder."""
    url = f"http://{COMFYUI_ADDRESS}/upload/image"
    with open(image_path, "rb") as f:
        image_data = f.read()

    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode("utf-8") + image_data + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    resp = urllib.request.urlopen(req)
    result = json.loads(resp.read())
    log.debug(f"[UPLOAD] ComfyUI response: {result}")
    return result


def queue_prompt(prompt, client_id):
    """Queue a prompt on ComfyUI and return the prompt_id."""
    prompt_id = str(uuid.uuid4())
    p = {"prompt": prompt, "client_id": client_id, "prompt_id": prompt_id}
    data = json.dumps(p).encode("utf-8")
    req = urllib.request.Request(f"http://{COMFYUI_ADDRESS}/prompt", data=data)
    urllib.request.urlopen(req).read()
    return prompt_id


def get_history(prompt_id):
    with urllib.request.urlopen(
        f"http://{COMFYUI_ADDRESS}/history/{prompt_id}"
    ) as response:
        return json.loads(response.read())


def get_image(filename, subfolder, folder_type):
    data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
    url_values = urllib.parse.urlencode(data)
    with urllib.request.urlopen(
        f"http://{COMFYUI_ADDRESS}/view?{url_values}"
    ) as response:
        return response.read()


def run_workflow(image_filename):
    """Load workflow, set the input image, run it, and return output image bytes."""
    with open(WORKFLOW_PATH, "r") as f:
        workflow = json.load(f)

    workflow["1"]["inputs"]["image"] = image_filename

    client_id = str(uuid.uuid4())
    ws_conn = websocket.WebSocket()
    ws_conn.connect(f"ws://{COMFYUI_ADDRESS}/ws?clientId={client_id}")

    prompt_id = queue_prompt(workflow, client_id)
    log.debug(f"[WS] Queued prompt_id={prompt_id}, waiting for completion...")

    while True:
        out = ws_conn.recv()
        if isinstance(out, str):
            message = json.loads(out)
            log.debug(f"[WS] Message: type={message.get('type')}, data={message.get('data')}")
            if message["type"] == "executing":
                data = message["data"]
                if data["node"] is None and data["prompt_id"] == prompt_id:
                    break
            elif message["type"] == "execution_error":
                log.error(f"[WS] Execution error: {message}")
                ws_conn.close()
                return None

    ws_conn.close()

    history = get_history(prompt_id)[prompt_id]
    log.debug(f"[HISTORY] Output keys: {list(history['outputs'].keys())}")
    for node_id, node_out in history["outputs"].items():
        log.debug(f"[HISTORY] Node {node_id}: {list(node_out.keys())}")

    node_output = history["outputs"].get("8", {})
    if "images" not in node_output:
        log.error(f"[HISTORY] No images in node 8 output. Full outputs: {json.dumps(history['outputs'], indent=2)}")
        return None

    image_info = node_output["images"][0]
    log.debug(f"[FETCH] Getting image: {image_info}")
    image_data = get_image(
        image_info["filename"], image_info["subfolder"], image_info["type"]
    )
    log.debug(f"[FETCH] Got {len(image_data)} bytes")
    return image_data


def save_temp_image(image_bytes, suffix=".png"):
    """Save image bytes to a temp file and return the path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(image_bytes)
    return path


def process_and_return(image_bytes, filename, output_dir):
    """Core logic: upload image to ComfyUI, run workflow, save result."""
    temp_path = save_temp_image(image_bytes)
    try:
        upload_resp = upload_image_to_comfyui(temp_path, filename)
        comfyui_filename = upload_resp.get("name", filename)
        log.debug(f"[PROCESS] ComfyUI filename: {comfyui_filename}")

        result_data = run_workflow(comfyui_filename)
        if result_data is None:
            return None, "No output image produced by workflow"

        output_path = os.path.join(output_dir, "output.png")
        with open(output_path, "wb") as f:
            f.write(result_data)

        return result_data, output_path
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@app.route("/process", methods=["POST"])
def process_image():
    """
    Process an image through the ComfyUI workflow.

    Accepts three input modes:
    1. File upload:  multipart/form-data with 'image' field
    2. Base64:       JSON body with {"base64": "<base64-encoded-image>"}
    3. URL:          JSON body with {"url": "https://example.com/image.png"}

    Returns JSON with output path and size, saves result as output.png.
    """
    image_bytes = None
    filename = "input.png"

    content_type = request.content_type or ""

    # Mode 1: File upload
    if "multipart/form-data" in content_type:
        if "image" not in request.files:
            return jsonify({"error": "No 'image' field in multipart form data."}), 400
        file = request.files["image"]
        if file.filename == "":
            return jsonify({"error": "Empty filename"}), 400
        filename = file.filename
        image_bytes = file.read()

    # Mode 2 & 3: JSON body (base64 or url)
    elif "application/json" in content_type:
        body = request.get_json(silent=True)
        if not body:
            return jsonify({"error": "Invalid JSON body."}), 400

        if "base64" in body:
            try:
                image_bytes = base64.b64decode(body["base64"])
            except Exception:
                return jsonify({"error": "Invalid base64 data."}), 400
            filename = body.get("filename", "input.png")

        elif "url" in body:
            try:
                req = urllib.request.Request(body["url"], headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    image_bytes = resp.read()
            except Exception as e:
                return jsonify({"error": f"Failed to download image from URL: {e}"}), 400
            # Extract filename from URL
            parsed = urllib.parse.urlparse(body["url"])
            filename = os.path.basename(parsed.path) or "input.png"

        else:
            return jsonify({"error": "JSON body must contain 'base64' or 'url' field."}), 400

    else:
        return jsonify({
            "error": "Unsupported content type. Use multipart/form-data (file upload), or application/json (base64/url)."
        }), 400

    if not image_bytes:
        return jsonify({"error": "Empty image data."}), 400

    try:
        result_data, output_path = process_and_return(image_bytes, filename, OUTPUT_DIR)
        if result_data is None:
            return jsonify({"error": output_path}), 500

        return jsonify({
            "status": "success",
            "output": output_path,
            "size_bytes": len(result_data),
        })

    except Exception as e:
        log.exception("[PROCESS] Error")
        return jsonify({"error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    print("Starting server on http://0.0.0.0:3169")
    print("Usage:")
    print("  File:   curl -X POST -F 'image=@photo.png' http://localhost:3169/process")
    print("  Base64: curl -X POST -H 'Content-Type: application/json' -d '{\"base64\":\"...\"}' http://localhost:3169/process")
    print("  URL:    curl -X POST -H 'Content-Type: application/json' -d '{\"url\":\"https://...\"}' http://localhost:3169/process")
    app.run(host="0.0.0.0", port=3169)
