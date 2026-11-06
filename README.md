# SaaS Log Monitor

Plateforme de monitoring et d'analyse de logs d'une application SaaS (Mini-Projet Big Data, scénario D).
Stack : **Elasticsearch 8 · Logstash 8 · Kibana 8 · MongoDB 7 · Redis 7 · Flask 3 · Docker Compose**.

## Prérequis
- Docker Desktop (Docker 24+ et Docker Compose 2+), avec **4 Go de RAM minimum** alloués
- Git, Python 3.11+ (uniquement pour le générateur de logs de test)

## Démarrage rapide
```bash
git clone <url-du-depot> && cd saas-log-monitor
cp .env.example .env
docker compose up -d --build
docker compose ps          # attendre que tous les services soient "healthy"
```
Temps estimé : 5 à 10 minutes au premier lancement (téléchargement des images), environ 1 à 2 minutes ensuite.

Arrêt : `docker compose down` (conserve les données) · `docker compose down -v` (supprime aussi les volumes).

## Vérifier que tout fonctionne
| Service | Adresse | Résultat attendu |
|---|---|---|
| Elasticsearch | http://localhost:9200 | JSON avec la version 8.x |
| Kibana | http://localhost:5601 | Interface Kibana |
| Logstash | http://localhost:9600 | JSON de statut |
| Application web | http://localhost:8000 | Page « Hello World » |
| Santé de l'application | http://localhost:8000/health | JSON : statut de ES, MongoDB, Redis |

Vérification automatique : `bash scripts/check_stack.sh`

## Générer et injecter des logs de test
```bash
python scripts/generate_logs.py -n 5000 -f json -o data/uploads/logs_test
```
Logstash lit `data/uploads/*.json` et indexe dans `saas-logs-YYYY.MM.dd`.
Dans Kibana : **Stack Management → Data Views → Create** → pattern `saas-logs-*`, champ temps `@timestamp`, puis **Discover**.

## Structure du dépôt
```
saas-log-monitor/
├── docker-compose.yml
├── .env.example            # modèle de configuration (le .env n'est pas versionné)
├── backend/                # application Flask (Dockerfile, requirements.txt, app/)
├── logstash/pipeline/      # pipelines Logstash (JSON en S1, CSV en S2)
├── elasticsearch/          # index template (S2)
├── kibana/                 # exports des dashboards (S4)
├── scripts/                # generate_logs.py, check_stack.sh
├── data/uploads/           # fichiers importés, surveillés par Logstash
└── docs/                   # analyse, UML, maquettes, architecture
```

## Variables d'environnement
Voir `.env.example` : `STACK_VERSION`, `ELASTICSEARCH_URL`, `MONGO_URI`, `REDIS_URL`, `SECRET_KEY`, `UPLOAD_DIR`, `MAX_UPLOAD_MB`, `LOG_LEVEL`.

> La sécurité d'Elasticsearch est désactivée pour le développement local. À activer avant tout déploiement réel.

## Avancement
| Sprint | Objectif | État |
|---|---|---|
| S1 | Analyse, conception, dépôt Git, Docker Compose | ✅ |
| S2 | Ingestion des logs (Logstash, upload, MongoDB) | 🔄 |
| S3 | API REST, recherche, Redis, authentification | ⏳ |
| S4 | Frontend et Kibana | ⏳ |
| S5 | Alerting | ⏳ |
| S6 | Temps réel | ⏳ |
| S7 | Tests et soutenance | ⏳ |

## Workflow Git
- `main` : version stable livrée · `develop` : intégration · `feature/<sprint>-<sujet>` : travail en cours.
- Messages de commit : `feat:`, `fix:`, `docs:`, `chore:` (ex. `feat: ajout du pipeline Logstash CSV`).
- Un tag par fin de sprint : `s1`, `s2`, …
