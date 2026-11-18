-- The v1.12 pre-Spring bootstrap connects to the mysql catalog before checking
-- that the game database exists. Grant catalog access through one timezone table,
-- not mysql.* access (which includes database credentials).
GRANT SELECT ON mysql.time_zone_name TO 'beidou'@'%';
-- Bundled Flyway 9 reads session variables when saving/restoring migration state.
GRANT SELECT ON performance_schema.user_variables_by_thread TO 'beidou'@'%';
