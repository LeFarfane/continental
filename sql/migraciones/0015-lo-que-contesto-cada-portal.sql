-- 0015 - el esquema `pedidos` gana una SEXTA tabla, `pedidos.lectura_de_portal`:
-- todo lo que contestó cada portal en cada consulta (2026-09-28, `lecturas_de_portal.py`).
--
-- SE CORRE A MANO, UNA VEZ, CON CREDENCIALES DE DUEÑO, como todas (ADR 0003):
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia --       -v ON_ERROR_STOP=1 < sql/migraciones/0015-lo-que-contesto-cada-portal.sql
--
-- A DIFERENCIA DE LA 0003 Y LA 0004, ESTA TRAE SU PROPIO GRANT al final: un
-- permiso no se puede dar sobre una tabla que no existía, y volver a correr
-- `crear_rol.sql` pide la contraseña del rol. `crear_rol.sql` lleva el mismo
-- GRANT para una base desde cero. Idempotente: correrla dos veces no rompe
-- nada. VA ANTES de desplegar el código que la escribe (si no, la captura
-- falla, lo dice en la bitácora y nada más: el precio se congela igual).

\set ON_ERROR_STOP on

BEGIN;

-- --------------------------------------------------------------------------
-- 6) Lo que contestó cada portal en cada consulta (2026-09-28).
-- --------------------------------------------------------------------------
--
-- EL DUEÑO PIDIÓ "TOMAR CADA CONSULTA COMO UNA OPORTUNIDAD": guardar todo lo
-- que devuelven los portales para preguntarle después, en Metabase, cómo se
-- mueven los precios de compra de cada proveedor. `precio_de_proveedor` guarda
-- UN precio por renglón y proveedor —el que empareja por EAN— y tiraba lo
-- demás; esta tabla guarda TODO, crudo (`lecturas_de_portal.py`):
--
--   - una fila por cada resultado que devolvió un portal (`posicion` 1..n);
--   - una fila por el proveedor que NO trajo ninguno (`posicion` 0), con su
--     `resultado` y su `motivo`: "quién no tenía el producto".
--
-- No se empareja nada al guardar: eso es de quien consulta. SOLO CRECE, como
-- `precio_de_proveedor` (ADR 0004).
--
-- `fecha` es el día de la farmacia (UTC-6 fijo, sin horario de verano desde
-- 2022, igual que `transito.ZONA_DE_LA_FARMACIA`), puesto por la base del
-- mismo `now()` que `consultado_en`. `AT TIME ZONE 'UTC'` con el nombre y no
-- `'-06'`: con un desfase escrito, Postgres usa la convención POSIX y lo lee
-- como UTC+6 (la trampa del ticket 25).
CREATE TABLE IF NOT EXISTS pedidos.lectura_de_portal (
    lectura_de_portal_id      bigint        GENERATED ALWAYS AS IDENTITY,
    negocio                   text          NOT NULL,
    consultado_en             timestamptz   NOT NULL DEFAULT now(),
    fecha                     date          NOT NULL
        DEFAULT ((now() AT TIME ZONE 'UTC') - interval '6 hours')::date,
    origen                    text          NOT NULL,
    termino                   text          NOT NULL,
    trabajo                   text          NOT NULL,
    renglon_id                bigint,
    proveedor                 text          NOT NULL,
    resultado                 text          NOT NULL,
    motivo                    text,
    detalle                   text,
    total_en_el_portal        integer       NOT NULL DEFAULT 0,
    posicion                  integer       NOT NULL,
    clave                     text,
    descripcion               text,
    precio_como_llego         text,
    precio                    numeric(12,2),
    precio_publico_como_llego text,
    precio_publico            numeric(12,2),
    existencia_como_llego     text,
    existencia                numeric(12,3),
    advertencia               text,

    CONSTRAINT pk_lectura_de_portal
        PRIMARY KEY (lectura_de_portal_id),

    -- Un trabajo de Doyle, un proveedor, una posición: una fila. Es lo que deja
    -- a Buscar mandar lo mismo en cada sondeo sin duplicar nada
    -- (`on conflict do nothing`).
    CONSTRAINT ux_lectura_trabajo
        UNIQUE (negocio, trabajo, proveedor, posicion),

    CONSTRAINT ck_lectura_negocio
        CHECK (negocio <> ''),

    CONSTRAINT ck_lectura_origen
        CHECK (origen IN ('lote', 'sonda del lote', 'consultar', 'completar', 'buscar')),

    CONSTRAINT ck_lectura_resultado
        CHECK (resultado IN ('con resultados', 'sin resultados', 'sin dato',
                             'no se sabe leer', 'no terminó')),

    -- La fila 0 es la del proveedor sin resultados, y solo ella.
    CONSTRAINT ck_lectura_posicion
        CHECK ((posicion = 0) = (resultado <> 'con resultados') AND posicion >= 0),

    -- Nunca un cero: el texto como llegó se guarda al lado (regla 4).
    CONSTRAINT ck_lectura_precio
        CHECK (precio > 0),

    CONSTRAINT ck_lectura_precio_publico
        CHECK (precio_publico > 0)
);

-- "¿Cómo se movió el precio de esta clave?", por día: la pregunta de Metabase.
CREATE INDEX IF NOT EXISTS ix_lectura_clave_fecha
    ON pedidos.lectura_de_portal (negocio, clave, fecha);

GRANT SELECT, INSERT, UPDATE ON pedidos.lectura_de_portal TO continental;

COMMIT;

SELECT count(*) AS columnas
  FROM information_schema.columns
 WHERE table_schema = 'pedidos' AND table_name = 'lectura_de_portal';

\echo ''
\echo '>> Arriba deben salir 23 columnas. Despues: sql/verificar_rol.sql.'
