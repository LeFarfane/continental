-- 0010 - la recepción sugerida: confirmar y rechazar "probablemente recibido"
-- (ticket 26, ADR 0014).
--
-- NO CREA NINGUNA TABLA: el esquema `pedidos` sigue teniendo CINCO. Lo que hace
-- es darle a `pedidos.renglon` seis columnas y cinco CHECK:
--
--   - LA RECEPCIÓN CONFIRMADA: `recibido_por`, `recibido_en` y
--     `recibido_con_compras` (los `compra_id` de SICAR que la sostienen). Una
--     persona juzgó la evidencia y dijo "llegó completo": el renglón pasa a
--     `recibido`, firmado.
--   - LO RECHAZADO: `compras_rechazadas`, `recepcion_rechazada_por` y
--     `recepcion_rechazada_en`. Una persona dijo "esa compra no es este
--     pedido": el renglón SIGUE `en tránsito` y esa compra ya no se le propone.
--
-- ## Para qué
--
-- Hasta el ticket 25 nada escribía `recibido`: lo que llegaba seguía en
-- tránsito, se veía atrasado a los N días, y lo retenido del ticket 24 -lo que
-- se vendió mientras venía- no volvía nunca. Desde aquí una compra de SICAR que
-- encaja con un renglón en tránsito -mismo proveedor, mismo producto, fecha
-- posterior al envío, NUNCA por folio- se PROPONE como "probablemente
-- recibido", y una persona la confirma o la rechaza.
--
-- **"Probablemente recibido" NO es un estado y NO está en ningún CHECK**: se
-- calcula cada vez que se mira, contra lo que el almacén tenga esa noche. Lo que
-- se guarda son las dos decisiones de una persona, y ésas son estas columnas.
-- El ADR 0014 tiene el porqué, con las alternativas descartadas.
--
-- ## Por qué `bigint[]` y no una tabla de cruce
--
-- Una tabla nueva obliga a volver a correr `sql/crear_rol.sql` -el paso que más
-- se olvida y el que peor avisa (ADR 0007, 0008, 0012)-. Lo que se guarda son
-- unas cuantas compras por renglón que no se consultan sueltas: se leen con el
-- renglón y se comparan con `&&` ("tienen algún elemento en común") en el
-- `WHERE` de confirmar. `bigint` porque es el tipo de `compra_id` en
-- `marts.fct_compras` (el `com_id` de SICAR).
--
--
-- SE CORRE A MANO, UNA VEZ, CON CREDENCIALES DE DUEÑO, igual que
-- `sql/crear_tablas.sql` y las migraciones 0001 a 0009, y por la misma razón
-- (ADR 0003): esto es DDL, y el rol `continental` no puede hacer DDL a
-- propósito. **No lo corre el servicio, no lo corre una prueba y no lo corre el
-- lote de la noche.**
--
-- Desde `~/proyectos/Continental` en atlas -- **plano, no anidado**--:
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 \
--       < sql/migraciones/0010-la-recepcion-sugerida.sql
--
-- `<` y no `-f`: con `docker exec`, el `-f` de psql busca el archivo DENTRO del
-- contenedor, donde este repo no está montado. `ON_ERROR_STOP=1` porque sin él
-- psql sigue tras un error y termina diciendo que todo salió bien.
--
--
-- ## HAY QUE CORRERLA ANTES DE DESPLEGAR EL CÓDIGO DEL TICKET 26
--
-- No es opcional: `_LEER_RENGLONES`, `_LEER_RENGLON_POR_ID`, `_LO_YA_PEDIDO` y
-- `_EN_TRANSITO` NOMBRAN las columnas nuevas, así que con el código nuevo y la
-- base vieja **la lista del día no se puede leer ni armar** -- "column
-- recibido_por does not exist"-- y la pantalla entera se queda en "no se pudo
-- armar el pedido sugerido". El lote de la noche también se corta. Es lo mismo
-- que pasó con la 0005 a la 0009. Las comprobaciones 34 y 35 de
-- `verificar_rol.sql` lo cazan.
--
--
-- ## `sql/crear_rol.sql` NO hace falta volver a correrlo
--
-- Igual que la 0005 a la 0009: aquí solo se agregan columnas y CHECK, y el
-- `GRANT SELECT, INSERT, UPDATE` es sobre la tabla entera -- no se usan
-- permisos por columna, a propósito--. Confirmar y rechazar son `UPDATE`, que el
-- rol ya tiene sobre `renglon` desde el ticket 07.
--
-- **Y DE `marts` TAMPOCO HACE FALTA NADA NUEVO.** Las dos lecturas de compras
-- -las compras desde el envío más viejo, y qué productos han aparecido alguna
-- vez en una compra- son sobre `marts.fct_compras` y `marts.dim_fecha`, que el
-- rol ya lee desde el ticket 07 (`crear_rol.sql`) y que farmacia-data otorga
-- desde el `config(grants=...)` de cada modelo. Hasta hoy nadie ejercitaba el
-- de `fct_compras`: si un `dbt build` se lo llevó, el bloque de la recepción lo
-- enseña como un hueco con su motivo -la lista sigue funcionando- y la
-- comprobación 9 de `verificar_rol.sql` lo dice.
--
-- Lo que SÍ conviene correr después es `sql/verificar_rol.sql`: sus
-- comprobaciones 34 y 35 son nuevas.
--
-- ## Es idempotente
--
-- Correrla dos veces no rompe nada y no cambia nada la segunda vez, igual que
-- las nueve anteriores: `ADD COLUMN IF NOT EXISTS` y `DROP CONSTRAINT IF EXISTS`
-- antes de cada `ADD CONSTRAINT`, todo en una transacción. Sobre una base con
-- renglones ya guardados no rechaza ninguno: hasta hoy ningún código escribía
-- `recibido` ni `recibido parcial`, así que `ck_renglon_recepcion` se cumple en
-- todas las filas que existen (la comprobación del final lo imprime).

SET client_encoding TO 'UTF8';

-- Que no lo corra quien no debe, igual que las nueve anteriores.
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
-- 1) La recepción confirmada: firma y compras
-- --------------------------------------------------------------------------
ALTER TABLE pedidos.renglon
    ADD COLUMN IF NOT EXISTS recibido_por text;
ALTER TABLE pedidos.renglon
    ADD COLUMN IF NOT EXISTS recibido_en timestamptz;
ALTER TABLE pedidos.renglon
    ADD COLUMN IF NOT EXISTS recibido_con_compras bigint[];

ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_recibido_por;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_recibido_por
        CHECK (recibido_por <> '');

-- RECIBIDO (COMPLETO O PARCIAL) SI Y SOLO SI HAY FIRMA Y HORA. El ticket 27
-- firma igual su `recibido parcial` y su marcado a mano.
ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_recepcion;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_recepcion
        CHECK ((estado IN ('recibido', 'recibido parcial'))
               = (recibido_por IS NOT NULL AND recibido_en IS NOT NULL));

-- LAS COMPRAS SOLO EN LO RECIBIDO, Y NUNCA UNA LISTA VACÍA. NULL en lo recibido
-- es el marcado a mano del ticket 27: sin compra de SICAR que lo sostenga.
ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_compras_de_la_recepcion;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_compras_de_la_recepcion
        CHECK (recibido_con_compras IS NULL
               OR (estado IN ('recibido', 'recibido parcial')
                   AND cardinality(recibido_con_compras) >= 1));

-- --------------------------------------------------------------------------
-- 2) Lo rechazado: qué compras no son este renglón, con la firma del último
-- --------------------------------------------------------------------------
ALTER TABLE pedidos.renglon
    ADD COLUMN IF NOT EXISTS compras_rechazadas bigint[];
ALTER TABLE pedidos.renglon
    ADD COLUMN IF NOT EXISTS recepcion_rechazada_por text;
ALTER TABLE pedidos.renglon
    ADD COLUMN IF NOT EXISTS recepcion_rechazada_en timestamptz;

ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_rechazo_por;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_rechazo_por
        CHECK (recepcion_rechazada_por <> '');

-- Las tres juntas o ninguna, y la lista nunca vacía. SIN relación con el
-- estado, a propósito: un renglón que rechazó una compra y después se recibió
-- con otra conserva su rechazo, que es parte de su historia.
ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_rechazo;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_rechazo
        CHECK ((compras_rechazadas IS NULL) = (recepcion_rechazada_por IS NULL)
               AND (compras_rechazadas IS NULL) = (recepcion_rechazada_en IS NULL)
               AND (compras_rechazadas IS NULL
                    OR cardinality(compras_rechazadas) >= 1));

-- --------------------------------------------------------------------------
-- Los comentarios
-- --------------------------------------------------------------------------

COMMENT ON COLUMN pedidos.renglon.recibido_por IS
    'Quién confirmó que llegó: juzgó la evidencia que la pantalla le enseñó '
    '(ADR 0014). Es una FIRMA, no un permiso. NULL si no está recibido.';

COMMENT ON COLUMN pedidos.renglon.recibido_en IS
    'Cuándo lo confirmó, instante con zona. NULL si no está recibido.';

COMMENT ON COLUMN pedidos.renglon.recibido_con_compras IS
    'Los compra_id de marts.fct_compras que sostienen la recepción (nunca el '
    'folio, de semántica no verificada). Una compra confirma un solo renglón. '
    'NULL si no está recibido, o si se recibió a mano sin compra (ticket 27).';

COMMENT ON COLUMN pedidos.renglon.compras_rechazadas IS
    'Los compra_id que una persona dijo que NO son este renglón: ya no se le '
    'proponen. El renglón sigue en tránsito; rechazar no es un estado.';

COMMENT ON COLUMN pedidos.renglon.recepcion_rechazada_por IS
    'Quién rechazó la última propuesta. Es una FIRMA, no un permiso.';

COMMENT ON COLUMN pedidos.renglon.recepcion_rechazada_en IS
    'Cuándo, instante con zona.';

COMMIT;


-- --------------------------------------------------------------------------
-- Qué quedó
-- --------------------------------------------------------------------------
--
-- Se imprime en vez de darse por hecho, igual que en las nueve anteriores.

SELECT con.conrelid::regclass         AS tabla,
       con.conname                    AS restriccion,
       pg_get_constraintdef(con.oid)  AS definicion
  FROM pg_constraint con
 WHERE con.conname IN ('ck_renglon_recibido_por', 'ck_renglon_recepcion',
                       'ck_renglon_compras_de_la_recepcion',
                       'ck_renglon_rechazo_por', 'ck_renglon_rechazo')
 ORDER BY con.conname;

\echo ''
\echo '>> COMPRUEBA ARRIBA: las cinco restricciones de la recepcion. Sin esta'
\echo '>> migracion, la lista del dia no se puede leer con el codigo del ticket 26.'
\echo ''
\echo '>> sql/crear_rol.sql NO hace falta volver a correrlo: esta migracion no crea'
\echo '>> ninguna tabla, el permiso es sobre la tabla entera, y marts.fct_compras ya'
\echo '>> estaba otorgada. Corre SI sql/verificar_rol.sql: sus comprobaciones 34 y'
\echo '>> 35 son nuevas.'
