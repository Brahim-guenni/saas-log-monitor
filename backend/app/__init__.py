"""Application Flask - plateforme de monitoring de logs SaaS (semaine 1 : squelette)."""
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from functools import wraps
import hashlib
import json
from pathlib import Path

from elasticsearch import Elasticsearch
from flask import Flask, jsonify, render_template_string, request
from pymongo import MongoClient
from redis import Redis
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash
from bson import ObjectId

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
    app.config["UPLOAD_DIR"] = os.getenv("UPLOAD_DIR", "/app/uploads")

    es = Elasticsearch(os.getenv("ELASTICSEARCH_URL", "http://elasticsearch:9200"))
    mongo = MongoClient(os.getenv("MONGO_URI", "mongodb://mongo:27017"), serverSelectionTimeoutMS=3000)
    redis = Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"), socket_connect_timeout=3)
    mongo_db = mongo[os.getenv("MONGO_DB", "saas_logs")]
    uploads_collection = mongo_db["uploads"]
    imports_collection = mongo_db["imports"]
    users_collection = mongo_db["users"]
    search_history_collection = mongo_db["search_history"]
    allowed_extensions = {".json", ".csv", ".txt"}

    admin_email = os.getenv("ADMIN_EMAIL", "admin@saas-log-monitor.local")
    admin_password = os.getenv("ADMIN_PASSWORD")
    if admin_password:
        existing_admin = users_collection.find_one({"email": admin_email.lower()})
        if existing_admin is None:
            users_collection.insert_one({
                "email": admin_email.lower(),
                "password_hash": generate_password_hash(admin_password),
                "role": "admin",
                "active": True,
                "created_at": datetime.now(timezone.utc),
            })

    def bearer_token():
        authorization = request.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            return authorization[7:].strip()
        return request.cookies.get("session_token")

    def current_user():
        token = bearer_token()
        if not token:
            return None
        cached = redis.get(f"session:{token}")
        if cached:
            try:
                session = json.loads(cached)
            except json.JSONDecodeError:
                redis.delete(f"session:{token}")
                return None
        else:
            return None
        user = users_collection.find_one({
            "_id": ObjectId(session["user_id"]),
            "active": True,
        }) if ObjectId.is_valid(session["user_id"]) else None
        return user

    def require_auth(required_role=None):
        def decorator(fn):
            @wraps(fn)
            def protected(*args, **kwargs):
                user = current_user()
                if user is None:
                    return jsonify({"error": "Unauthorized"}), 401
                if required_role == "admin" and user["role"] != "admin":
                    return jsonify({"error": "Forbidden"}), 403
                request.current_user = user
                return fn(*args, **kwargs)
            return protected
        return decorator

    def rate_limit():
        token = bearer_token()
        identity = token or request.remote_addr or "unknown"
        key = f"api:rate:{hashlib.sha256(identity.encode()).hexdigest()}"
        count = redis.incr(key)
        if count == 1:
            redis.expire(key, 60)
        if count > 100:
            response = jsonify({"error": "Too many requests"})
            response.status_code = 429
            response.headers["Retry-After"] = str(redis.ttl(key))
            return response
        return None

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

    @app.post("/api/v1/auth/login")
    def login():
        body = request.get_json(silent=True) or {}
        email = str(body.get("email", "")).strip().lower()
        password = str(body.get("password", ""))
        if not email or not password:
            return jsonify({"error": "Email and password are required"}), 400

        user = users_collection.find_one({"email": email})
        if user is None or not user.get("active", False):
            return jsonify({"error": "Invalid credentials"}), 401
        if not check_password_hash(user["password_hash"], password):
            return jsonify({"error": "Invalid credentials"}), 401

        token = secrets.token_urlsafe(32)
        session = {
            "user_id": str(user["_id"]),
            "email": user["email"],
            "role": user["role"],
        }
        redis.setex(f"session:{token}", 3600, json.dumps(session))
        return jsonify({
            "token": token,
            "expires_in": 3600,
            "user": {"id": str(user["_id"]), "email": user["email"], "role": user["role"]},
        }), 200

    @app.post("/api/v1/auth/logout")
    @require_auth()
    def logout():
        token = bearer_token()
        redis.delete(f"session:{token}")
        return jsonify({"message": "Logged out"}), 200

    @app.get("/api/v1/auth/me")
    @require_auth()
    def auth_me():
        user = request.current_user
        return jsonify({
            "id": str(user["_id"]),
            "email": user["email"],
            "role": user["role"],
        }), 200

    @app.get("/api/v1/users")
    @require_auth(required_role="admin")
    def list_users():
        limited = rate_limit()
        if limited:
            return limited
        users = []
        for user in users_collection.find({}, {"password_hash": 0}).sort("created_at", -1):
            users.append({
                "id": str(user["_id"]),
                "email": user["email"],
                "role": user["role"],
                "active": user.get("active", False),
                "created_at": user["created_at"].isoformat(),
            })
        return jsonify({"users": users}), 200

    @app.post("/api/v1/users")
    @require_auth(required_role="admin")
    def create_user():
        limited = rate_limit()
        if limited:
            return limited
        body = request.get_json(silent=True) or {}
        email = str(body.get("email", "")).strip().lower()
        password = str(body.get("password", ""))
        role = str(body.get("role", "analyst")).lower()
        if not email or not password:
            return jsonify({"error": "Email and password are required"}), 400
        if role not in {"analyst", "admin"}:
            return jsonify({"error": "Role must be analyst or admin"}), 400
        if users_collection.find_one({"email": email}):
            return jsonify({"error": "Email already exists"}), 409

        result = users_collection.insert_one({
            "email": email,
            "password_hash": generate_password_hash(password),
            "role": role,
            "active": True,
            "created_at": datetime.now(timezone.utc),
        })
        return jsonify({
            "id": str(result.inserted_id),
            "email": email,
            "role": role,
            "active": True,
        }), 201

    @app.patch("/api/v1/users/<user_id>")
    @require_auth(required_role="admin")
    def update_user(user_id):
        limited = rate_limit()
        if limited:
            return limited
        if not ObjectId.is_valid(user_id):
            return jsonify({"error": "Invalid user ID"}), 400
        body = request.get_json(silent=True) or {}
        updates = {}
        if "active" in body:
            updates["active"] = bool(body["active"])
        if "role" in body:
            role = str(body["role"]).lower()
            if role not in {"analyst", "admin"}:
                return jsonify({"error": "Role must be analyst or admin"}), 400
            updates["role"] = role
        if not updates:
            return jsonify({"error": "No valid fields provided"}), 400
        result = users_collection.update_one({"_id": ObjectId(user_id)}, {"$set": updates})
        if result.matched_count == 0:
            return jsonify({"error": "User not found"}), 404
        return jsonify({"id": user_id, **updates}), 200

    def elastic_query(params):
        must = []
        filters = []

        text = params.get("q", "").strip()
        if text:
            must.append({"multi_match": {
                "query": text,
                "fields": ["message^3", "service", "endpoint", "sql_query"],
                "type": "best_fields",
            }})

        date_from = params.get("date_from") or params.get("start")
        date_to = params.get("date_to") or params.get("end")
        if date_from or date_to:
            date_range = {}
            if date_from:
                date_range["gte"] = date_from
            if date_to:
                date_range["lte"] = date_to
            filters.append({"range": {"@timestamp": date_range}})

        for field, param in (
            ("level", "level"),
            ("service", "service"),
            ("endpoint", "endpoint"),
            ("status_code", "status_code"),
        ):
            value = params.get(param)
            if value:
                if param == "status_code":
                    try:
                        filters.append({"term": {field: int(value)}})
                    except ValueError:
                        raise ValueError("status_code must be an integer")
                else:
                    filters.append({"match": {field: value}})

        return {"bool": {"must": must or [{"match_all": {}}], "filter": filters}}

    def serialize_hit(hit):
        source = dict(hit["_source"])
        source["_id"] = hit["_id"]
        source["_index"] = hit["_index"]
        return source

    @app.get("/search")
    @app.get("/api/v1/search")
    @require_auth()
    def search_logs():
        limited = rate_limit()
        if limited:
            return limited

        try:
            page = max(int(request.args.get("page", 1)), 1)
            size = min(max(int(request.args.get("size", 50)), 1), 50)
            if request.args.get("date_from") and request.args.get("date_to"):
                if request.args["date_from"] > request.args["date_to"]:
                    raise ValueError("date_from must be before date_to")
            query = elastic_query(request.args)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        sort_param = request.args.get("sort", "date_desc").lower()
        sort = {
            "date_asc": [{"@timestamp": {"order": "asc"}}],
            "level": [{"@timestamp": {"order": "desc"}}],
            "service": [{"@timestamp": {"order": "desc"}}],
        }.get(sort_param, [{"@timestamp": {"order": "desc"}}])

        cache_payload = {
            "query": dict(request.args),
            "page": page,
            "size": size,
            "sort": sort_param,
        }
        cache_key = "cache:search:" + hashlib.sha256(
            json.dumps(cache_payload, sort_keys=True, default=str).encode()
        ).hexdigest()
        cached = redis.get(cache_key)
        if cached:
            return jsonify(json.loads(cached)), 200

        try:
            response = es.search(
                index="saas-logs-*",
                query=query,
                from_= (page - 1) * size,
                size=size,
                sort=sort,
            )
        except Exception as exc:
            log.exception("Elasticsearch search failed")
            return jsonify({"error": "Elasticsearch unavailable", "details": str(exc)[:200]}), 503

        total = response["hits"]["total"]["value"]
        result = {
            "total": total,
            "page": page,
            "size": size,
            "pages": max((total + size - 1) // size, 1),
            "sort": sort_param,
            "logs": [serialize_hit(hit) for hit in response["hits"]["hits"]],
        }
        redis.setex(cache_key, 60, json.dumps(result, default=str))

        try:
            search_history_collection.insert_one({
                "user_id": str(request.current_user["_id"]),
                "filters": dict(request.args),
                "searched_at": datetime.now(timezone.utc),
                "total": total,
            })
        except Exception:
            log.exception("Search history could not be saved")

        return jsonify(result), 200

    @app.get("/api/v1/logs")
    @require_auth()
    def list_logs():
        return search_logs()

    @app.get("/api/v1/logs/<log_id>")
    @require_auth()
    def log_detail(log_id):
        limited = rate_limit()
        if limited:
            return limited
        try:
            response = es.search(
                index="saas-logs-*",
                size=1,
                query={"ids": {"values": [log_id]}},
            )
            hits = response["hits"]["hits"]
        except Exception as exc:
            log.exception("Elasticsearch log detail failed")
            return jsonify({"error": "Elasticsearch unavailable", "details": str(exc)[:200]}), 503
        if not hits:
            return jsonify({"error": "Log not found"}), 404
        return jsonify({"log": serialize_hit(hits[0])}), 200

    @app.get("/api/v1/files")
    @require_auth()
    def list_files():
        limited = rate_limit()
        if limited:
            return limited
        page = max(int(request.args.get("page", 1)), 1)
        size = min(max(int(request.args.get("size", 50)), 1), 100)
        query = {}
        status = request.args.get("status")
        date_from = request.args.get("date_from")
        date_to = request.args.get("date_to")
        filters = []
        if status:
            filters.append({"status": status})
        if date_from:
            filters.append({"uploaded_at": {"$gte": datetime.fromisoformat(date_from)}})
        if date_to:
            filters.append({"uploaded_at": {"$lte": datetime.fromisoformat(date_to)}})
        if filters:
            query = filters[0] if len(filters) == 1 else {"$and": filters}

        source_collection = imports_collection
        if imports_collection.count_documents(query) == 0:
            source_collection = uploads_collection
        cursor = source_collection.find(query).sort("uploaded_at", -1)
        total = source_collection.count_documents(query)
        documents = list(cursor.skip((page - 1) * size).limit(size))
        files = []
        for document in documents:
            files.append({
                "id": str(document["_id"]),
                "filename": document["filename"],
                "format": document["extension"].lstrip("."),
                "size_bytes": document["size_bytes"],
                "status": document["status"],
                "uploaded_at": document["uploaded_at"].isoformat(),
            })
        return jsonify({
            "total": total,
            "page": page,
            "size": size,
            "pages": max((total + size - 1) // size, 1),
            "files": files,
        }), 200

    @app.get("/api/v1/stats")
    @require_auth()
    def stats():
        limited = rate_limit()
        if limited:
            return limited
        cache_key = "cache:stats:s3"
        cached = redis.get(cache_key)
        if cached:
            return jsonify(json.loads(cached)), 200

        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            total = es.count(index="saas-logs-*")["count"]
            today = es.count(
                index="saas-logs-*",
                query={"range": {"@timestamp": {"gte": today_start.isoformat()}}},
            )["count"]
            errors = es.count(
                index="saas-logs-*",
                query={"range": {"status_code": {"gte": 500, "lt": 600}}},
            )["count"]
        except Exception as exc:
            log.exception("Elasticsearch stats failed")
            return jsonify({"error": "Elasticsearch unavailable", "details": str(exc)[:200]}), 503

        result = {
            "total_logs": total,
            "logs_today": today,
            "errors_5xx": errors,
            "files_count": (
                imports_collection.count_documents({})
                if imports_collection.count_documents({}) > 0
                else uploads_collection.count_documents({})
            ),
        }
        redis.setex(cache_key, 60, json.dumps(result))
        return jsonify(result), 200

    @app.get("/api/docs")
    def api_docs():
        return render_template_string("""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>SaaS Log Monitor API</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"></head>
<body><div id="swagger-ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>SwaggerUIBundle({url:'/openapi.json',dom_id:'#swagger-ui'});</script>
</body></html>""")

    @app.get("/openapi.json")
    def openapi():
        return jsonify({
            "openapi": "3.0.3",
            "info": {"title": "SaaS Log Monitor API", "version": "1.0.0"},
            "servers": [{"url": "/"}],
            "components": {
                "securitySchemes": {
                    "BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"},
                }
            },
            "paths": {
                "/api/v1/auth/login": {"post": {"summary": "Login and create a Redis session"}},
                "/api/v1/auth/me": {"get": {"summary": "Get the current user", "security": [{"BearerAuth": []}]}},
                "/api/v1/logs": {"get": {"summary": "List and search logs", "security": [{"BearerAuth": []}]}},
                "/api/v1/logs/{id}": {"get": {"summary": "Get one log", "security": [{"BearerAuth": []}]}},
                "/api/v1/files": {"get": {"summary": "List imported files", "security": [{"BearerAuth": []}]}},
                "/api/v1/stats": {"get": {"summary": "Get platform statistics", "security": [{"BearerAuth": []}]}},
            },
        }), 200

    @app.post("/upload")
    def upload():
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            return jsonify({"error": "No file provided"}), 400

        filename = secure_filename(upload.filename)
        suffix = Path(filename).suffix.lower()
        if suffix not in allowed_extensions:
            return jsonify({"error": "Only CSV, JSON and TXT files are accepted"}), 400

        content = upload.read()
        if not content:
            return jsonify({"error": "The uploaded file is empty"}), 400

        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            return jsonify({"error": "The uploaded file must use UTF-8 encoding"}), 400

        if suffix == ".json":
            import json

            if not text.strip():
                return jsonify({"error": "The uploaded JSON file is empty"}), 400
            try:
                try:
                    json.loads(text)
                except json.JSONDecodeError:
                    for line in text.splitlines():
                        if line.strip():
                            json.loads(line)
            except json.JSONDecodeError as exc:
                return jsonify({"error": "Invalid JSON", "details": str(exc)}), 400
        elif suffix == ".csv":
            import csv
            from io import StringIO

            try:
                reader = csv.reader(StringIO(text))
                header = next(reader)
            except (StopIteration, csv.Error) as exc:
                return jsonify({"error": "Invalid CSV", "details": str(exc)}), 400
            if len(header) != 12:
                return jsonify({"error": "CSV must contain exactly 12 columns"}), 400
        elif not text.strip():
            return jsonify({"error": "The uploaded TXT file is empty"}), 400

        upload_dir = Path(app.config["UPLOAD_DIR"])
        upload_dir.mkdir(parents=True, exist_ok=True)
        destination = upload_dir / filename
        if destination.exists():
            stem = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
            destination = upload_dir / f"{Path(filename).stem}-{stem}{suffix}"

        destination.write_bytes(content)
        metadata = {
            "filename": destination.name,
            "original_filename": filename,
            "content_type": upload.mimetype,
            "extension": suffix,
            "size_bytes": len(content),
            "uploaded_at": datetime.now(timezone.utc),
            "status": "uploaded",
        }

        try:
            result = uploads_collection.insert_one(metadata)
            metadata["_id"] = str(result.inserted_id)
            imports_collection.insert_one({
                **{key: value for key, value in metadata.items() if key != "_id"},
                "_id": result.inserted_id,
                "format": suffix.lstrip("."),
                "nb_lines": None,
                "nb_errors": 0,
            })
        except Exception as exc:
            destination.unlink(missing_ok=True)
            log.exception("Impossible d'enregistrer les metadonnees d'upload")
            return jsonify({"error": "Upload metadata could not be saved", "details": str(exc)[:200]}), 503

        metadata["uploaded_at"] = metadata["uploaded_at"].isoformat()
        return jsonify({"message": "File uploaded successfully", "file": metadata}), 201

    return app
