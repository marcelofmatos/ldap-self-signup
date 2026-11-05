#!/bin/sh
set -e
# Primeira linha do log: a versão, antes de qualquer config ou serviço externo.
echo "ldap-self-signup ${APP_VERSION:-dev} iniciando"
# 1 worker: rate limit e lock de criação são em memória (1 réplica).
exec gunicorn --bind 0.0.0.0:8000 --workers 1 --threads 4 "app.wsgi:app"
