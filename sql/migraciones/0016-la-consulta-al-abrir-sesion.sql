-- 0016 - un origen más para `pedidos.lectura_de_portal`: 'al abrir sesión'
-- (2026-09-28). Es la consulta de la lista del día que dispara «Ya entré» en
-- un portal —LEVIC, cuya sesión muere a los ~20 minutos sin uso—, solo en ese
-- portal.
--
-- SE CORRE A MANO, UNA VEZ, CON CREDENCIALES DE DUEÑO (ADR 0003), ANTES de
-- desplegar el código que la usa: sin ella, esas lecturas rebotan en el CHECK,
-- se dice en la bitácora y el precio se congela igual.
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 < sql/migraciones/0016-la-consulta-al-abrir-sesion.sql
--
-- No crea tabla: no hace falta volver a correr `crear_rol.sql`. Idempotente.

\set ON_ERROR_STOP on

BEGIN;

ALTER TABLE pedidos.lectura_de_portal DROP CONSTRAINT IF EXISTS ck_lectura_origen;
ALTER TABLE pedidos.lectura_de_portal ADD CONSTRAINT ck_lectura_origen
    CHECK (origen IN ('lote', 'sonda del lote', 'consultar', 'completar', 'buscar',
                      'al abrir sesión'));

COMMIT;

SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_lectura_origen';

\echo ''
\echo '>> Arriba debe salir el CHECK con al abrir sesión, CON SU ACENTO.'
