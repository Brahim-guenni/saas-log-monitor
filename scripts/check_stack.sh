#!/usr/bin/env bash
# Verifie que tous les services de la stack repondent.
ok(){ printf "  [OK]   %s\n" "$1"; }
ko(){ printf "  [FAIL] %s\n" "$1"; FAIL=1; }
FAIL=0
echo "Verification de la stack..."
curl -sf http://localhost:9200/_cluster/health >/dev/null && ok "Elasticsearch  :9200" || ko "Elasticsearch  :9200"
curl -sf http://localhost:9600 >/dev/null && ok "Logstash       :9600" || ko "Logstash       :9600"
curl -sf http://localhost:5601/api/status >/dev/null && ok "Kibana         :5601" || ko "Kibana         :5601"
curl -sf http://localhost:8000/health >/dev/null && ok "Backend Flask  :8000" || ko "Backend Flask  :8000"
docker compose exec -T mongo mongosh --quiet --eval "db.adminCommand('ping').ok" 2>/dev/null | grep -q 1 && ok "MongoDB" || ko "MongoDB"
docker compose exec -T redis redis-cli ping 2>/dev/null | grep -q PONG && ok "Redis" || ko "Redis"
echo -n "  Logs indexes : "; curl -s "http://localhost:9200/saas-logs-*/_count" | grep -o '"count":[0-9]*' || echo "aucun index"
exit $FAIL
