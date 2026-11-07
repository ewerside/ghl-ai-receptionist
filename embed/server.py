"""Tiny HTTP service that embeds a question with fastembed (bge-small-en-v1.5).

n8n cannot run fastembed, so the flow calls this service on the Docker network:
POST /embed {"text": "..."} -> {"embedding": "[0.01,...]"} (a pgvector literal).
GET /health -> {"ok": true}. Standard library only, besides fastembed.
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastembed import TextEmbedding

MODEL = TextEmbedding(
    model_name="BAAI/bge-small-en-v1.5",
    cache_dir=os.environ.get("FASTEMBED_CACHE", "/models"),
)
# The bge model card recommends this instruction for short queries; the KB loader
# embeds passages without it (same as the support-agent-rag project).
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
MAX_CHARS = 2000


def embed(text: str) -> str:
    vector = next(iter(MODEL.query_embed(QUERY_PREFIX + text[:MAX_CHARS])))
    return "[" + ",".join(f"{v:.6f}" for v in vector) + "]"


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/embed":
            self._send(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            text = json.loads(self.rfile.read(length))["text"]
            if not isinstance(text, str) or not text.strip():
                raise ValueError("text must be a non-empty string")
        except (ValueError, KeyError, TypeError) as exc:
            self._send(400, {"error": str(exc)})
            return
        self._send(200, {"embedding": embed(text)})

    def log_message(self, fmt: str, *args) -> None:
        # One short line per request, without the question text.
        print(
            f"{self.command} {self.path} {args[1] if len(args) > 1 else ''}", flush=True
        )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
