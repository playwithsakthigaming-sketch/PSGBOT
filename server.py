from flask import Flask, request, send_from_directory, jsonify, abort
import os
import uuid

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
BASE_URL = "https://files.psgfamily.online"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


@app.route("/")
def home():
    return "File server running", 200


@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]

    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    ext = file.filename.split(".")[-1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(UPLOAD_FOLDER, filename)

    file.save(path)

    return jsonify({
        "url": f"{BASE_URL}/{filename}"
    })


@app.route("/<filename>")
def serve_file(filename):
    path = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.exists(path):
        abort(404)
    return send_from_directory(UPLOAD_FOLDER, filename)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
