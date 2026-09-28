-- El rol con el que Metabase lee lo de Continental (2026-09-28).
--
-- El dueño decidió agregar a Continental en Metabase "como otra base de datos,
-- así de simple", sin pasar por el dbt de farmacia-data (el ADR 0001 descartó
-- ese camino por el ciclo que arma). Este rol es esa puerta, y es angosta a
-- propósito: SOLO `SELECT` y SOLO sobre `pedidos.lectura_de_portal`. No ve los
-- pedidos, ni los renglones, ni las firmas, ni `marts` —eso ya lo ve Metabase
-- por su propia conexión—.
--
-- SE CORRE A MANO, CON CREDENCIALES DE DUEÑO, y es idempotente: la segunda vez
-- solo vuelve a poner la contraseña que se le pase.
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 -v password="LA_CONTRASENA" < sql/crear_rol_metabase.sql
--
-- La contraseña NO vive en este repo. En atlas se genera una vez y se guarda
-- en `~/.config/continental/metabase_continental` (permisos 600); de ahí la
-- copia quien da de alta la base en Metabase (Admin → Bases de datos →
-- Agregar: PostgreSQL, el mismo host y puerto que la conexión de farmacia,
-- base `farmacia`, usuario `metabase_continental`).

\set ON_ERROR_STOP on

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'metabase_continental') THEN
        CREATE ROLE metabase_continental LOGIN;
    END IF;
END $$;

ALTER ROLE metabase_continental WITH LOGIN PASSWORD :'password';

GRANT CONNECT ON DATABASE farmacia TO metabase_continental;
GRANT USAGE ON SCHEMA pedidos TO metabase_continental;
GRANT SELECT ON pedidos.lectura_de_portal TO metabase_continental;

-- Defensivo, igual que en `crear_rol.sql`: nada de crear tablas en `public`.
REVOKE CREATE ON SCHEMA public FROM metabase_continental;

SELECT table_schema || '.' || table_name AS puede_leer
  FROM information_schema.role_table_grants
 WHERE grantee = 'metabase_continental' AND privilege_type = 'SELECT'
 ORDER BY 1;

\echo ''
\echo '>> Arriba debe salir UNA sola tabla: pedidos.lectura_de_portal.'
