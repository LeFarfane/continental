-- 0007 - el avance de la captura: tachar un renglón, firmado (ticket 22, ADR 0010).
--
-- NO CREA NINGUNA TABLA: el esquema `pedidos` sigue teniendo CINCO. Lo que hace
-- son dos cosas sobre `pedidos.renglon`:
--
--   1. Gana `capturado_por` y `capturado_en`: quién dijo haber tecleado ese
--      renglón en el portal del proveedor de su pedido, y cuándo.
--   2. Entran `ck_renglon_capturado_por` (la firma vacía no existe) y
--      `ck_renglon_captura` (quién y cuándo van juntos).
--
-- SE CORRE A MANO, UNA VEZ, CON CREDENCIALES DE DUEÑO, igual que
-- `sql/crear_tablas.sql` y las migraciones 0001 a 0006, y por la misma razón
-- (ADR 0003): esto es DDL, y el rol `continental` no puede hacer DDL a
-- propósito. **No lo corre el servicio, no lo corre una prueba y no lo corre el
-- lote de la noche.**
--
-- Desde `~/proyectos/Continental` en atlas -- **plano, no anidado**--:
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 \
--       < sql/migraciones/0007-el-avance-de-la-captura.sql
--
-- `<` y no `-f`: con `docker exec`, el `-f` de psql busca el archivo DENTRO del
-- contenedor, donde este repo no está montado. `ON_ERROR_STOP=1` porque sin él
-- psql sigue tras un error y termina diciendo que todo salió bien.
--
--
-- ## HAY QUE CORRERLA ANTES DE DESPLEGAR EL CÓDIGO DEL TICKET 22
--
-- No es opcional ni se puede dejar para después: `_LEER_RENGLONES` y
-- `_LEER_RENGLON_POR_ID` NOMBRAN las dos columnas nuevas, así que con el código
-- nuevo y la base vieja **la lista del día no se puede leer** -- "column
-- capturado_por does not exist"-- y la pantalla entera se queda en "no se pudo
-- armar el pedido sugerido". Es lo mismo que pasó con la 0005 y la 0006. La
-- comprobación 29 de `verificar_rol.sql` lo caza.
--
--
-- ## `sql/crear_rol.sql` NO hace falta volver a correrlo
--
-- Igual que la 0005 y la 0006, y al revés que la 0003 y la 0004, que estrenaban
-- una TABLA: aquí solo se agregan columnas y restricciones, y el `GRANT SELECT,
-- INSERT, UPDATE` es sobre la tabla entera -- no se usan permisos por columna,
-- a propósito--.
--
-- Lo que SÍ conviene correr después es `sql/verificar_rol.sql`: su comprobación
-- 29 es nueva y lee DE VUELTA, desde el catálogo, que la restricción y las dos
-- columnas estén.
--
--
-- ## POR QUÉ EN LA TABLA Y NO EN EL NAVEGADOR
--
-- Es la decisión cara del ticket y está entera en el ADR 0010. En corto: con el
-- avance en `localStorage`, dos pestañas del mismo pedido divergen en silencio,
-- cambiar de máquina a la mitad de 40 renglones lo pierde entero, y la marca
-- que LLEVA a enviar -- la quinta casilla del ticket-- no diría quién la puso.
--
-- ## POR QUÉ COLUMNAS Y NO UN ESTADO NUEVO DEL RENGLÓN
--
-- Porque un renglón dentro de un borrador sigue 'abierto' (ticket 20), y
-- cuatro sentencias -- asignar, soltar, descartar y ajustar-- llevan
-- `estado = 'abierto'` en su WHERE. Un estado 'capturado' entre 'abierto' y
-- 'en tránsito' las dejaría saltarse el renglón en silencio: volver a partir
-- no lo movería y el total del pedido dejaría de contarlo. Por eso
-- `ck_renglon_estado` NO se toca aquí.
--
-- ## Es idempotente
--
-- Correrlo dos veces no rompe nada y no cambia nada la segunda vez, igual que
-- las seis anteriores: `ADD COLUMN IF NOT EXISTS` para las columnas y
-- `DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT` para las restricciones, en una
-- transacción. Si el `ADD` fallara, el `DROP` se va con él.
--
-- No hace falta migrar dato alguno: las dos columnas entran NULLables y sin
-- DEFAULT, y NULL en las dos es "nadie lo ha tachado", que es la verdad de todo
-- renglón que exista hoy. Un DEFAULT inventaría una declaración que nadie hizo.

SET client_encoding TO 'UTF8';

-- Que no lo corra quien no debe, igual que las seis anteriores.
DO $guardia$
BEGIN
    IF current_user = 'continental' THEN
        RAISE EXCEPTION '%',
            'Esta migración se corre con credenciales de DUEÑO (usuario '
            || 'farmacia), no con el rol acotado continental: el rol no tiene '
            || 'ALTER sobre sus tablas y eso es deliberado (ADR 0003).';
    END IF;
END
$guardia$;

BEGIN;

-- --------------------------------------------------------------------------
-- 1) `pedidos.renglon` gana la marca de captura
-- --------------------------------------------------------------------------
ALTER TABLE pedidos.renglon
    ADD COLUMN IF NOT EXISTS capturado_por text;

ALTER TABLE pedidos.renglon
    ADD COLUMN IF NOT EXISTS capturado_en timestamptz;

-- --------------------------------------------------------------------------
-- 2) La firma no puede ir vacía, y quién y cuándo van juntos
-- --------------------------------------------------------------------------
--
-- La cadena vacía no existe en ninguna columna de texto de este esquema: se
-- compara igual que un dato y empareja con cualquier otra vacía.
ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_capturado_por;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_capturado_por
        CHECK (capturado_por <> '');

-- Pareada como las otras cuatro firmas del esquema, pero contra NADA más: tachar
-- no es un estado, así que el CHECK solo dice que quién y cuándo van juntos.
ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_captura;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_captura
        CHECK ((capturado_por IS NULL) = (capturado_en IS NULL));

-- --------------------------------------------------------------------------
-- Los comentarios
-- --------------------------------------------------------------------------

COMMENT ON COLUMN pedidos.renglon.capturado_por IS
    'Quién dijo haberlo tecleado ya en el portal del proveedor de su pedido, '
    'según Cf-Access-Authenticated-User-Email. Es una FIRMA, no un permiso. '
    'NULL = nadie lo ha tachado. No es un estado: el renglón sigue abierto.';

COMMENT ON COLUMN pedidos.renglon.capturado_en IS
    'Cuándo lo dijo, instante con zona. NULL = nadie lo ha tachado.';

COMMIT;


-- --------------------------------------------------------------------------
-- Qué quedó
-- --------------------------------------------------------------------------
--
-- Se imprime en vez de darse por hecho, igual que en las seis anteriores.

SELECT a.attname                            AS columna,
       format_type(a.atttypid, a.atttypmod) AS tipo,
       NOT a.attnotnull                     AS admite_nulos
  FROM pg_attribute a
 WHERE a.attrelid = to_regclass('pedidos.renglon')
   AND a.attname IN ('capturado_por', 'capturado_en')
   AND NOT a.attisdropped
 ORDER BY a.attnum;

SELECT con.conname                   AS restriccion,
       pg_get_constraintdef(con.oid) AS definicion
  FROM pg_constraint con
 WHERE con.conrelid = to_regclass('pedidos.renglon')
   AND con.conname IN ('ck_renglon_capturado_por', 'ck_renglon_captura')
 ORDER BY con.conname;

\echo ''
\echo '>> COMPRUEBA ARRIBA dos columnas (text y timestamptz, las dos admiten nulos)'
\echo '>> y dos restricciones. Si falta cualquiera, la lista del dia no se puede'
\echo '>> leer con el codigo del ticket 22.'
\echo ''
\echo '>> sql/crear_rol.sql NO hace falta volver a correrlo: esta migracion no crea'
\echo '>> ninguna tabla y el GRANT es sobre la tabla entera. Corre SI'
\echo '>> sql/verificar_rol.sql: su comprobacion 29 es nueva.'
