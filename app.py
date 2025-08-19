from flask import Flask, jsonify
import os

app = Flask(__name__)

@app.get("/")
def root():
    return "Hello, to Cloud Run! "

@app.get("/healthz")
def healthz():
    # put basic checks here if you want (DB ping, etc.)
    return jsonify(status="ok"), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
