-- 0012 - reabrir la lista cerrada, firmado (ADR 0016).
--
-- NO CREA NINGUNA TABLA: el esquema `pedidos` sigue teniendo CINCO. Lo que hace
-- es darle a `pedidos.pedido_sugerido` dos columnas y dos CHECK:
--
--   - `reabierto_por` (text) y `reabierto_en` (timestamptz): la firma de la
--     ÚLTIMA vez que alguien deshizo un cierre. Las dos admiten nulos y NO
--     tienen DEFAULT.
--   - `ck_pedido_sugerido_reabierto_por`: la firma no va vacía.
--   - `ck_pedido_sugerido_reapertura`: las dos o ninguna.
--
-- ## Para qué
--
-- Cerrar una lista mueve el corte (ticket 09): la siguiente acumula desde el
-- día siguiente, y lo que la cerrada tenía sin pedir se da por atendido --
-- incluido lo que faltó de un parcial y lo vendido mientras un pedido viajaba,
-- que no vuelve nunca--. Desde el ADR 0016 la pantalla lo avisa antes de
-- cerrar, y deja DESHACER el cierre mientras ninguna lista se haya armado
-- después. Deshacer es `cerrado` -> `abierto`, y va firmado: "¿quién la
-- reabrió?" es la pregunta que alguien va a hacer cuando una lista diga cerrada
-- a las 14:00 y abierta a las 14:05.
--
-- ## NO ROMPE EL CÓDIGO QUE HOY CORRE EN ATLAS
--
-- Se puede correr antes de desplegar sin que el servicio de hoy lo note, y es
-- a propósito:
--
--   - Ninguna sentencia del código viejo nombra estas columnas. Su `INSERT` de
--     la lista no las escribe y quedan en NULL: por eso NO son `NOT NULL` y NO
--     llevan DEFAULT.
--   - Los dos CHECK aceptan NULL en las dos columnas, que es lo único que el
--     código viejo deja.
--   - El CHECK pareado NO mira el estado: el `_CERRAR` y el `_VENCER` viejos
--     no tienen que saber de la firma. Y no se toca `ck_pedido_sugerido_estado`
--     ni `ck_pedido_sugerido_cierre`: reabrir usa `abierto` y `cerrado_en =
--     NULL`, que ya valían.
--   - No toca `pedidos.renglon` ni `pedidos.pedido`.
--
-- ## HAY QUE CORRERLA ANTES DE DESPLEGAR EL CÓDIGO DEL ADR 0016
--
-- No es opcional: `_LEER_LISTA`, `_LEER_LISTA_POR_ID`, `_INSERTAR_LISTA` y
-- `_CERRAR` DEVUELVEN las columnas nuevas, así que con el código nuevo y la
-- base vieja la lista del día no se puede leer ni armar -- "column
-- reabierto_por does not exist"-- y la pantalla se queda en "no se pudo armar
-- el pedido sugerido". El lote de la noche también se corta. La comprobación
-- 38 de `verificar_rol.sql` lo caza.
--
--
-- SE CORRE A MANO, UNA VEZ, CON CREDENCIALES DE DUEÑO, igual que
-- `sql/crear_tablas.sql` y las migraciones 0001 a 0011, y por la misma razón
-- (ADR 0003): esto es DDL, y el rol `continental` no puede hacer DDL a
-- propósito. **No lo corre el servicio, no lo corre una prueba y no lo corre el
-- lote de la noche.**
--
-- Desde `~/proyectos/Continental` en atlas -- **plano, no anidado**--:
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 \
--       < sql/migraciones/0012-reabrir-la-lista-cerrada.sql
--
-- `<` y no `-f`: con `docker exec`, el `-f` de psql busca el archivo DENTRO del
-- contenedor, donde este repo no está montado. `ON_ERROR_STOP=1` porque sin él
-- psql sigue tras un error y termina diciendo que todo salió bien.
--
--
-- ## `sql/crear_rol.sql` NO hace falta volver a correrlo
--
-- Igual que la 0005 a la 0011: aquí solo se agregan columnas y CHECK, y el
-- `GRANT SELECT, INSERT, UPDATE` es sobre la tabla entera -- no se usan
-- permisos por columna, a propósito--. Reabrir es un `UPDATE`, que el rol ya
-- tiene sobre `pedido_sugerido` desde el ticket 07.
--
-- Lo que SÍ conviene correr después es `sql/verificar_rol.sql`: su comprobación
-- 38 es nueva.
--
-- ## Sin relleno
--
-- Ninguna lista se reabrió antes de hoy -ningún código lo hacía-, así que NULL
-- es la verdad de toda fila existente.
--
-- ## Es idempotente
--
-- Correrla dos veces no rompe nada y no cambia nada la segunda vez, igual que
-- las once anteriores: `ADD COLUMN IF NOT EXISTS` y `DROP CONSTRAINT IF EXISTS`
-- antes de cada `ADD CONSTRAINT`, todo en una transacción.

SET client_encoding TO 'UTF8';

-- Que no lo corra quien no debe, igual que las once anteriores.
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
-- `pedidos.pedido_sugerido` gana la firma de la reapertura
-- --------------------------------------------------------------------------
ALTER TABLE pedidos.pedido_sugerido
    ADD COLUMN IF NOT EXISTS reabierto_por text;
ALTER TABLE pedidos.pedido_sugerido
    ADD COLUMN IF NOT EXISTS reabierto_en timestamptz;

ALTER TABLE pedidos.pedido_sugerido
    DROP CONSTRAINT IF EXISTS ck_pedido_sugerido_reabierto_por;
ALTER TABLE pedidos.pedido_sugerido
    ADD CONSTRAINT ck_pedido_sugerido_reabierto_por
        CHECK (reabierto_por <> '');

ALTER TABLE pedidos.pedido_sugerido
    DROP CONSTRAINT IF EXISTS ck_pedido_sugerido_reapertura;
ALTER TABLE pedidos.pedido_sugerido
    ADD CONSTRAINT ck_pedido_sugerido_reapertura
        CHECK ((reabierto_por IS NULL) = (reabierto_en IS NULL));

COMMENT ON COLUMN pedidos.pedido_sugerido.reabierto_por IS
    'Quién deshizo el último cierre de esta lista (correo de Cloudflare Access: '
    'firma, no permiso). NULL si nunca se reabrió. Se queda al volver a cerrar '
    '(ADR 0016).';

COMMENT ON COLUMN pedidos.pedido_sugerido.reabierto_en IS
    'Cuándo se deshizo el último cierre (instante real, con zona). La hora del '
    'cierre deshecho queda en la bitácora: cerrado_en vuelve a NULL al reabrir.';

COMMIT;


-- --------------------------------------------------------------------------
-- Qué quedó
-- --------------------------------------------------------------------------
--
-- Se imprime en vez de darse por hecho, igual que en las once anteriores.

SELECT a.attname                            AS columna,
       format_type(a.atttypid, a.atttypmod) AS tipo,
       NOT a.attnotnull                     AS admite_nulos
  FROM pg_attribute a
 WHERE a.attrelid = to_regclass('pedidos.pedido_sugerido')
   AND a.attname IN ('reabierto_por', 'reabierto_en')
   AND NOT a.attisdropped
 ORDER BY a.attname;

SELECT con.conname                    AS restriccion,
       pg_get_constraintdef(con.oid)  AS definicion
  FROM pg_constraint con
 WHERE con.conrelid = to_regclass('pedidos.pedido_sugerido')
   AND con.conname IN ('ck_pedido_sugerido_reabierto_por',
                       'ck_pedido_sugerido_reapertura')
 ORDER BY con.conname;

\echo ''
\echo '>> COMPRUEBA ARRIBA: dos columnas que admiten nulos y dos restricciones.'
\echo '>> Sin esta migracion, la lista del dia no se puede leer con el codigo del'
\echo '>> ADR 0016. El codigo de antes no la nota: se puede correr primero.'
\echo ''
\echo '>> sql/crear_rol.sql NO hace falta volver a correrlo: esta migracion no crea'
\echo '>> ninguna tabla y el permiso es sobre la tabla entera. Corre SI'
\echo '>> sql/verificar_rol.sql: su comprobacion 38 es nueva.'
