#!/usr/bin/env python3
"""Genere des logs de test (CSV ou JSON ligne par ligne) pour la plateforme de monitoring SaaS.

Exemples :
    python scripts/generate_logs.py -n 5000 -f json -o data/uploads/logs_test
    python scripts/generate_logs.py -n 5000 -f csv  -o data/uploads/logs_test
"""
import argparse
import csv
import json
import random
from datetime import datetime, timedelta, timezone

ENDPOINTS = ["/api/login", "/api/users", "/api/orders", "/api/products",
             "/api/search", "/api/reports", "/api/payments"]
METHODS = ["GET", "GET", "GET", "POST", "PUT", "DELETE"]
STATUS = [200] * 80 + [201] * 5 + [301, 400, 401, 403, 404] * 2 + [500, 502, 503] * 2
SERVICES = ["web-api", "auth-service", "billing-service"]
SQL = ["SELECT * FROM orders WHERE user_id = ?",
       "SELECT * FROM products JOIN stock",
       "UPDATE users SET last_login = NOW()"]
FIELDS = ["timestamp", "log_type", "level", "service", "method", "endpoint",
          "status_code", "response_time_ms", "client_ip", "message",
          "sql_query", "query_duration_ms"]


def make_log(ts):
    status = random.choice(STATUS)
    rt = max(5, random.gauss(120, 60))
    if status >= 500:
        rt *= random.uniform(3, 8)
    level = "ERROR" if status >= 500 else "WARN" if status >= 400 else "INFO"
    log = {
        "timestamp": ts.isoformat(timespec="milliseconds") + "Z",
        "level": level,
        "service": random.choice(SERVICES),
        "method": random.choice(METHODS),
        "endpoint": random.choice(ENDPOINTS),
        "status_code": status,
        "response_time_ms": round(rt, 1),
        "client_ip": f"192.168.{random.randint(0, 10)}.{random.randint(1, 254)}",
        "message": "Internal server error" if status >= 500 else "Request handled",
    }
    if random.random() < 0.04:  # requete SQL lente
        log.update(log_type="slow_query", sql_query=random.choice(SQL),
                   query_duration_ms=round(random.uniform(800, 5000), 1), level="WARN")
    else:
        log["log_type"] = "http_request"
    return log


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", "--count", type=int, default=5000)
    ap.add_argument("-f", "--format", choices=["csv", "json"], default="json")
    ap.add_argument("-o", "--output", default="logs_test")
    a = ap.parse_args()

    start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
    logs = [make_log(start + timedelta(seconds=i * 86400 / a.count)) for i in range(a.count)]
    path = f"{a.output}.{a.format}"
    with open(path, "w", newline="", encoding="utf-8") as f:
        if a.format == "json":
            for entry in logs:
                f.write(json.dumps(entry) + "\n")   # un objet JSON par ligne (NDJSON)
        else:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(logs)
    print(f"{len(logs)} logs ecrits dans {path}")


if __name__ == "__main__":
    main()
