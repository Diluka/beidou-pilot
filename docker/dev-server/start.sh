#!/bin/sh
set -eu
umask 077
cd /opt/server_backup
runtime=/run/beidou-runtime

# Keep the disposable development admin on its configured password.
mkdir -p "$runtime/migration" "$runtime/.beidou-cli"
game_ip=$(getent ahostsv4 beidou-server-all | awk 'NR==1 {print $1}')
[ -n "$game_ip" ] || { echo '无法解析开发服服务地址。' >&2; exit 2; }
awk -v ip="$game_ip" '/^    (wan-host|lan-host|localhost):/ {sub("127.0.0.1", ip)} {print}' \
    /run/beidou-dev/application.yml > "$runtime/application.yml"
admin_hash=$(printf '%s' "$BEIDOU_DEV_ADMIN_PASSWORD" | sha512sum | cut -d ' ' -f 1)
printf '%s\n' "UPDATE accounts SET password = '$admin_hash'" \
    "WHERE id = 1 AND name = 'admin';" \
    > "$runtime/migration/afterMigrate__dev_seed_password.sql"
printf '{"configured":true,"server":"http://127.0.0.1:8686","username":"admin","password":"%s"}\n' \
    "$BEIDOU_DEV_ADMIN_PASSWORD" > "$runtime/.beidou-cli/config.json"
set -- ./jdk-*/bin/java
chmod +x "$1"
exec "$1" -Xms256m -Xmx2g -jar BeiDou.jar \
    --spring.config.location="$runtime/application.yml" \
    --spring.flyway.locations="classpath:db/migration,filesystem:$runtime/migration"
