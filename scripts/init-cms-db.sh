#!/bin/sh
# Apply CMS database initialization to an existing project PostgreSQL container.
# CMS_DATABASE_PASSWORD=<local secret> sh scripts/init-cms-db.sh <container-name>
set -eu
: "${CMS_DATABASE_PASSWORD:?Set CMS_DATABASE_PASSWORD to the CMS database password}"
: "${1:?Pass the project PostgreSQL container name}"
export CMS_DATABASE_PASSWORD
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
docker exec -i --env CMS_DATABASE_PASSWORD "$1" sh -s < "$script_dir/../infra/postgres/init-cms.sh"
