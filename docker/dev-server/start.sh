#!/bin/sh
set -eu
umask 077
cd /opt/server_backup
runtime=/run/beidou-runtime
for secret in "$BEIDOU_DEV_DB_PASSWORD" "$BEIDOU_DEV_JWT_SECRET" "$BEIDOU_DEV_ADMIN_PASSWORD"; do
    case "$secret" in *[!a-f0-9]*) echo '开发服密钥须使用小写十六进制。' >&2; exit 2;; esac
    [ "${#secret}" -ge 32 ] || { echo '开发服密钥至少需要 32 个十六进制字符。' >&2; exit 2; }
done
printf '%s  %s\n' 15cd8eabc3b72790856cc39a80368c615035336141560532e4e1e3490eab9ffd /run/beidou-dev/beidou-cli.jar | sha256sum --check --status || {
    echo '管理 CLI 不是已核验的官方 1.0.5 JAR。' >&2; exit 2;
}

# The game must advertise its client-facing address, not its backend-network IP.
game_ip=$(getent ahostsv4 beidou-game | awk 'NR == 1 {print $1}')
[ -n "$game_ip" ] || { echo '无法解析开发服 game 网络地址。' >&2; exit 2; }
# v1.12 reads concrete YAML before Spring runs; preserve other release defaults.
awk -v ip="$game_ip" '
  /jdbc:mysql:\/\/localhost:3306/ {sub("localhost:3306", "beidou-db:3306"); sub("useSSL=false", "useSSL=false\\&allowPublicKeyRetrieval=true")}
  /^      username:/ {$0="      username: beidou"}
  /^      password:/ {$0="      password: \"" ENVIRON["BEIDOU_DEV_DB_PASSWORD"] "\""}
  /^  secret:/ {$0="  secret: \"" ENVIRON["BEIDOU_DEV_JWT_SECRET"] "\""}
  /^    (wan-host|lan-host|localhost):/ {sub("127.0.0.1", ip)}
  {print}
' application.yml > "$runtime/application.yml"

# Only replace the known packaged seed credential. Never reset an existing admin.
# This Flyway bootstrap callback runs before the game accepts clients.
mkdir -p "$runtime/migration" "$runtime/.beidou-cli"
admin_hash=$(printf '%s' "$BEIDOU_DEV_ADMIN_PASSWORD" | sha512sum | cut -d ' ' -f 1)
printf '%s\n' "UPDATE accounts SET password = '$admin_hash'" \
    "WHERE id = 1 AND name = 'admin'" \
    'AND BINARY password = '\''$2y$12$aFD9BDeUocDMY1X4tDYDyeJw/HhkQwCQWs3KAY7gCaRG0cpqJcaL.'\'';' \
    > "$runtime/migration/afterMigrate__dev_seed_password.sql"
printf '{"configured":true,"server":"http://127.0.0.1:8686","username":"admin","password":"%s"}\n' \
    "$BEIDOU_DEV_ADMIN_PASSWORD" > "$runtime/.beidou-cli/config.json"
unset BEIDOU_DEV_ADMIN_PASSWORD BEIDOU_DEV_DB_PASSWORD BEIDOU_DEV_JWT_SECRET
set -- ./jdk-*/bin/java
chmod +x "$1"
exec "$1" -Xms256m -Xmx2g -jar BeiDou.jar --spring.config.location="$runtime/application.yml" \
    --spring.flyway.locations="classpath:db/migration,filesystem:$runtime/migration"
