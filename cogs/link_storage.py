from flask import Flask, request, send_from_directory, jsonify, abort
import os
import uuid

app = Flask(__name__)

# ===============================
# CONFIG
# ===============================
UPLOAD_FOLDER = "uploads"
BASE_URL = "https://files.psgfamily.online"
MAX_FILE_SIZE_MB = 25  # max upload size

app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE_MB * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ===============================
# HOME ROUTE (health check)
# ===============================
@app.route("/")
def home():
    return "File server running", 200


# ===============================
# UPLOAD ENDPOINT
# ===============================
@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]

    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    # Get file extension
    if "." in file.filename:
        ext = file.filename.rsplit(".", 1)[1].lower()
    else:
        ext = "dat"

    # Generate random filename
    filename = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(UPLOAD_FOLDER, filename)

    try:
        file.save(path)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "url": f"{BASE_URL}/{filename}"
    })


# ===============================
# SERVE FILES
# ===============================
@app.route("/<filename>")
def serve_file(filename):
    path = os.path.join(UPLOAD_FOLDER, filename)

    if not os.path.exists(path):
        abort(404)

    return send_from_directory(UPLOAD_FOLDER, filename)


# ===============================
# MAIN (Railway-compatible port)
# ===============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # Railway uses this
    app.run(host="0.0.0.0", port=port)
