"""Application Flask - plateforme de monitoring de logs SaaS (semaine 1 : squelette)."""
import logging
import os
import time

from elasticsearch import Elasticsearch
from flask import Flask, jsonify, render_template_string
from pymongo import MongoClient
from redis import Redis

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
log = logging.getLogger("webapp")

HOME = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>SaaS Log Monitor</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{font-family:Arial,sans-serif;max-width:640px;margin:4rem auto;padding:0 1rem}
h1{color:#1F4E79}code{background:#f4f4f4;padding:2px 6px;border-radius:4px}</style></head>
<body><h1>Hello World - SaaS Log Monitor</h1>
<p>Le backend Flask fonctionne. Etat des services : <a href="/health"><code>/health</code></a></p>
</body></html>"""


def _check(fn):
    """Execute un test de connectivite et mesure sa duree."""
    start = time.perf_counter()
    try:
        fn()
        status, error = "up", None
    except Exception as exc:  # noqa: BLE001
        status, error = "down", str(exc)[:200]
    return {"status": status, "response_ms": round((time.perf_counter() - start) * 1000, 1),
            **({"error": error} if error else {})}


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev")
    app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "100")) * 1024 * 1024

    es = Elasticsearch(os.getenv("ELASTICSEARCH_URL", "http://elasticsearch:9200"))
    mongo = MongoClient(os.getenv("MONGO_URI", "mongodb://mongo:27017"), serverSelectionTimeoutMS=3000)
    redis = Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"), socket_connect_timeout=3)

    def run_checks():
        return {
            "elasticsearch": _check(lambda: es.info()),
            "mongodb": _check(lambda: mongo.admin.command("ping")),
            "redis": _check(lambda: redis.ping()),
        }

    # Test de connectivite au demarrage (resultat journalise, ne bloque pas l'application)
    for name, res in run_checks().items():
        (log.info if res["status"] == "up" else log.warning)("Connexion %s : %s", name, res["status"])

    @app.get("/")
    def home():
        return render_template_string(HOME)

    @app.get("/health")
    def health():
        checks = run_checks()
        ups = [c["status"] == "up" for c in checks.values()]
        status = "healthy" if all(ups) else ("down" if not any(ups) else "degraded")
        # 200 tant que l'application repond (utilise par le healthcheck Docker)
        return jsonify({"status": status, "checks": checks}), 200

    return app
