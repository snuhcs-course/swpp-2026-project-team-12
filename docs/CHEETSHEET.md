# Start Server
```bash
cd /home/swpp26-13/talkdock/swpp-2026-project-team-12
conda activate talkdock
python backend/manage.py migrate
```

## Neo4j
```bash
sudo docker start talkdock-neo4j
```

## Nginx
```bash
mkdir -p deploy/nginx/run
nginx -t -p "$PWD/deploy/nginx/" -c nginx.conf
nginx -p "$PWD/deploy/nginx/" -c nginx.conf
# reload
nginx -p "$PWD/deploy/nginx/" -c nginx.conf -s reload
```

## Django
```bash
TELEMETRY_ENVIRONMENT=production bash deploy/run-service.sh api
```

## Push worker
```bash
TELEMETRY_ENVIRONMENT=production bash deploy/run-service.sh push
```

## Dashboard — server
```bash
TELEMETRY_ENVIRONMENT=production python backend/manage.py run_telemetry_dashboard --port 8765 --nginx-log "$PWD/deploy/nginx/run/access.log"
```

## Dashboard — laptop
```bash
ssh -N -T -L 127.0.0.1:13000:127.0.0.1:8765 SSH_HOST_ALIAS
# http://127.0.0.1:13000
# Ctrl+C
```

# Constructor
```bash
GRAPHITI_AUTO_CONSTRUCTION=0 bash deploy/run-service.sh api
# separate terminal
bash deploy/run-service.sh construction
# one family
python backend/manage.py run_construction_worker --family-id FAMILY_ID
```

# Change Password
```bash
python backend/manage.py changepassword USERNAME
```
