#!/bin/sh
set -eu
umask 077
cd /opt/server_backup
runtime=/run/beidou-runtime

# Keep the disposable development admin on its configured password.
mkdir -p "$runtime/migration" "$runtime/.beidou-cli"
admin_hash=$(printf '%s' "$BEIDOU_DEV_ADMIN_PASSWORD" | sha512sum | cut -d ' ' -f 1)
printf '%s\n' "UPDATE accounts SET password = '$admin_hash'" \
    "WHERE id = 1 AND name = 'admin';" \
    > "$runtime/migration/afterMigrate__dev_seed_password.sql"
printf '{"configured":true,"server":"http://127.0.0.1:8686","username":"admin","password":"%s"}\n' \
    "$BEIDOU_DEV_ADMIN_PASSWORD" > "$runtime/.beidou-cli/config.json"
set -- ./jdk-*/bin/java
chmod +x "$1"
exec "$1" -Xms256m -Xmx2g -jar BeiDou.jar \
    --spring.config.location=/run/beidou-dev/application.yml \
    --spring.flyway.locations="classpath:db/migration,filesystem:$runtime/migration"
