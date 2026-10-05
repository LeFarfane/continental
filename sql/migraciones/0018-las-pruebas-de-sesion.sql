-- 0018 - el esquema `pedidos` gana una SÉPTIMA tabla, `pedidos.prueba_de_sesion`:
-- lo que dijo un portal cada vez que alguien apretó «Probar» en la tarjeta de
-- una sesión (2026-10-05, ADR 0024, ticket 02 de `sesiones-al-abrir`).
--
-- SE CORRE A MANO, UNA VEZ, CON CREDENCIALES DE DUEÑO, como todas (ADR 0003):
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 \
--       < sql/migraciones/0018-las-pruebas-de-sesion.sql
--
-- COMO LA 0015, TRAE SU PROPIO GRANT al final: un permiso no se puede dar
-- sobre una tabla que no existía, y volver a correr `crear_rol.sql` pide la
-- contraseña del rol. `crear_rol.sql` lleva el mismo GRANT para una base desde
-- cero. Idempotente: correrla dos veces no rompe nada.
--
-- **VA ANTES DE DESPLEGAR el código que la lee.** `GET /api/sesiones` la lee
-- junto con las consultas guardadas; sin la tabla, las tarjetas dicen solo lo
-- de Doyle y avisan que no se pudieron leer las pruebas. `verificar --forma`
-- detiene el despliegue (paso 4 de `desplegar.sh`, ADR 0017) y nombra este
-- archivo: la tabla nueva es la columna testigo.
--
-- **A DIFERENCIA DE LAS DEMÁS, el rol NO recibe UPDATE** aquí: solo SELECT e
-- INSERT. Una prueba es un hecho del pasado y la tabla solo crece (regla 6 de
-- CLAUDE.md: el permiso es la garantía, no la buena intención del código). La
-- comprobación 6 de `verificar_rol.sql` exceptúa esta tabla, y la 41 comprueba
-- que de verdad no pueda actualizarla.

\set ON_ERROR_STOP on

SET client_encoding TO 'UTF8';

BEGIN;

CREATE TABLE IF NOT EXISTS pedidos.prueba_de_sesion (
    prueba_de_sesion_id bigint        GENERATED ALWAYS AS IDENTITY,
    negocio             text          NOT NULL,
    proveedor           text          NOT NULL,
    probada_en          timestamptz   NOT NULL DEFAULT now(),
    resultado           text          NOT NULL,

    CONSTRAINT pk_prueba_de_sesion
        PRIMARY KEY (prueba_de_sesion_id),

    CONSTRAINT ck_prueba_negocio
        CHECK (negocio <> ''),

    CONSTRAINT ck_prueba_resultado
        CHECK (resultado IN ('sirvió', 'caducada'))
);

CREATE INDEX IF NOT EXISTS ix_prueba_proveedor_cuando
    ON pedidos.prueba_de_sesion (negocio, proveedor, probada_en);

GRANT SELECT, INSERT ON pedidos.prueba_de_sesion TO continental;

COMMIT;

SELECT count(*) AS columnas
  FROM information_schema.columns
 WHERE table_schema = 'pedidos' AND table_name = 'prueba_de_sesion';

\echo ''
\echo '>> Arriba deben salir 5 columnas. Despues: sql/verificar_rol.sql.'
