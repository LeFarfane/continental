-- 0011 - recibido parcial y marcado a mano (ticket 27, ADR 0015).
--
-- NO CREA NINGUNA TABLA: el esquema `pedidos` sigue teniendo CINCO. Lo que hace
-- es darle a `pedidos.renglon` dos columnas y tres CHECK:
--
--   - `piezas_recibidas`: CUÁNTAS LLEGARON. Lo dice una persona -a mano- o la
--     evidencia de SICAR que una persona juzgó (ticket 26). De ahí sale si el
--     renglón es `recibido` (llegaron al menos las pedidas) o `recibido
--     parcial` (llegaron menos), y cuánto faltó.
--   - `piezas_que_faltaron`: las piezas de un pedido anterior que llegó DE
--     MENOS y que este renglón trae de vuelta, ya sumadas a su
--     `cantidad_propuesta`. Casi siempre cero.
--
-- ## Para qué
--
-- Hasta el ticket 26 un renglón en tránsito solo salía de ahí con una compra de
-- SICAR que trajera al menos lo pedido. El caso de todos los días -el proveedor
-- manda la mitad- no tenía salida, y lo que nunca deja compra en SICAR
-- (QuePharma, el 17.7% del catálogo) tampoco. Desde aquí:
--
--   - se dice cuántas piezas llegaron de un renglón, a mano o con la evidencia;
--   - si llegaron menos, el renglón queda `recibido parcial` y LO QUE FALTÓ
--     VUELVE A PROPONERSE en la siguiente lista, COMO PIEZAS: pedí 10,
--     llegaron 6, la siguiente lista suma 4 a lo vendido (ADR 0015);
--   - la cifra se corrige -la segunda factura, un error de captura- mientras lo
--     que faltó no lo haya atendido una lista posterior.
--
-- **El estado del PEDIDO no se toca aquí, y es a propósito.** `recibido` y
-- `recibido parcial` del pedido se CALCULAN de sus renglones cada vez que se
-- mira (ADR 0015): `ck_pedido_estado` sigue con `borrador`, `enviado` y
-- `cancelado`, que son lo que una persona declara.
--
--
-- SE CORRE A MANO, UNA VEZ, CON CREDENCIALES DE DUEÑO, igual que
-- `sql/crear_tablas.sql` y las migraciones 0001 a 0010, y por la misma razón
-- (ADR 0003): esto es DDL, y el rol `continental` no puede hacer DDL a
-- propósito. **No lo corre el servicio, no lo corre una prueba y no lo corre el
-- lote de la noche.**
--
-- Desde `~/proyectos/Continental` en atlas -- **plano, no anidado**--:
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 \
--       < sql/migraciones/0011-recibido-parcial-y-a-mano.sql
--
-- `<` y no `-f`: con `docker exec`, el `-f` de psql busca el archivo DENTRO del
-- contenedor, donde este repo no está montado. `ON_ERROR_STOP=1` porque sin él
-- psql sigue tras un error y termina diciendo que todo salió bien.
--
--
-- ## HAY QUE CORRERLA ANTES DE DESPLEGAR EL CÓDIGO DEL TICKET 27
--
-- No es opcional: `_LEER_RENGLONES`, `_LEER_RENGLON_POR_ID`, `_LO_YA_PEDIDO` y
-- `_EN_TRANSITO` NOMBRAN las columnas nuevas, y `_INSERTAR_RENGLONES` escribe
-- `piezas_que_faltaron`, así que con el código nuevo y la base vieja **la lista
-- del día no se puede leer ni armar** -- "column piezas_recibidas does not
-- exist"-- y el lote de la noche se corta. Es lo mismo que pasó con la 0005 a
-- la 0010. Las comprobaciones 36 y 37 de `verificar_rol.sql` lo cazan.
--
-- Y va DESPUÉS de la 0010: nombra `recibido_con_compras` en sus comentarios y
-- su relleno depende de que `recibido` ya exista con firma.
--
--
-- ## `sql/crear_rol.sql` NO hace falta volver a correrlo
--
-- Igual que la 0005 a la 0010: aquí solo se agregan columnas y CHECK, y el
-- `GRANT SELECT, INSERT, UPDATE` es sobre la tabla entera -- no se usan
-- permisos por columna, a propósito--. Recibir a mano, recibir parcial y
-- corregir son `UPDATE`, que el rol ya tiene sobre `renglon` desde el ticket
-- 07. De `marts` no se lee nada nuevo.
--
-- Lo que SÍ conviene correr después es `sql/verificar_rol.sql`: sus
-- comprobaciones 36 y 37 son nuevas.
--
-- ## El relleno de lo que ya se recibió
--
-- Lo confirmado con el ticket 26 ANTES de esta migración dijo "llegó completo"
-- sin decir cuántas piezas. Se llena con lo PEDIDO -`coalesce(cantidad_final,
-- cantidad_propuesta)`-, que es exactamente lo que "completo" afirmaba como
-- mínimo; la cifra exacta de la evidencia está en `marts.fct_compras`, por sus
-- `recibido_con_compras`, si alguna vez importa. Va ANTES de los CHECK: con
-- ellos puestos primero, ninguna fila recibida los cumpliría y la migración
-- rebotaría.
--
-- Un `recibido parcial` de antes de hoy NO puede existir -ningún código lo
-- escribía- y NO se rellena: no hay manera honesta de saber cuántas llegaron.
-- Si aparece uno, la guardia de abajo detiene la migración con su motivo, en
-- vez de inventar una cifra.
--
-- ## Es idempotente
--
-- Correrla dos veces no rompe nada y no cambia nada la segunda vez, igual que
-- las diez anteriores: `ADD COLUMN IF NOT EXISTS`, el relleno solo toca lo que
-- sigue en NULL, y `DROP CONSTRAINT IF EXISTS` antes de cada `ADD CONSTRAINT`,
-- todo en una transacción.

SET client_encoding TO 'UTF8';

-- Que no lo corra quien no debe, igual que las diez anteriores.
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
-- 1) Cuántas llegaron
-- --------------------------------------------------------------------------
ALTER TABLE pedidos.renglon
    ADD COLUMN IF NOT EXISTS piezas_recibidas numeric(12,3);

-- Lo confirmado por el 26 dijo "llegó completo": se llena con lo pedido.
UPDATE pedidos.renglon
   SET piezas_recibidas = coalesce(cantidad_final, cantidad_propuesta)
 WHERE estado = 'recibido'
   AND piezas_recibidas IS NULL;

-- Un parcial sin cifra no se inventa: se detiene aquí, con su motivo.
DO $sin_cifra$
BEGIN
    IF EXISTS (SELECT 1 FROM pedidos.renglon
                WHERE estado = 'recibido parcial'
                  AND piezas_recibidas IS NULL) THEN
        RAISE EXCEPTION '%',
            'Hay renglones en «recibido parcial» sin piezas_recibidas. Ningún '
            || 'código anterior al ticket 27 escribía ese estado: alguien lo '
            || 'puso a mano. No se inventa cuántas llegaron -de eso sale lo que '
            || 'vuelve a proponerse-: pon la cifra a mano y vuelve a correr esto.';
    END IF;
END
$sin_cifra$;

-- RECIBIDO (COMPLETO O PARCIAL) SI Y SOLO SI DICE CUÁNTAS LLEGARON, Y NUNCA
-- CERO: cero no es recibir -si no llegó nada, el renglón sigue en camino-.
ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_piezas_recibidas;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_piezas_recibidas
        CHECK ((estado IN ('recibido', 'recibido parcial'))
                   = (piezas_recibidas IS NOT NULL)
               AND (piezas_recibidas IS NULL OR piezas_recibidas > 0));

-- `recibido` ES QUE LLEGARON AL MENOS LAS PEDIDAS; `recibido parcial`, QUE
-- LLEGARON MENOS. Lo pedido es la corrección de la persona si la hubo. Un
-- `recibido` con piezas de menos cerraría el renglón en falso y lo que faltó
-- no volvería nunca: la tabla lo impide aunque el código se equivoque.
ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_completo_o_parcial;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_completo_o_parcial
        CHECK (piezas_recibidas IS NULL
               OR ((estado = 'recibido')
                   = (piezas_recibidas >= coalesce(cantidad_final, cantidad_propuesta))));

-- --------------------------------------------------------------------------
-- 2) Lo que faltó y este renglón trae de vuelta
-- --------------------------------------------------------------------------
ALTER TABLE pedidos.renglon
    ADD COLUMN IF NOT EXISTS piezas_que_faltaron integer NOT NULL DEFAULT 0;

-- Se SUMA a lo vendido para dar la propuesta: cabe en ella y nunca es negativo.
ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_piezas_que_faltaron;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_piezas_que_faltaron
        CHECK (piezas_que_faltaron >= 0
               AND piezas_que_faltaron <= cantidad_propuesta);

-- --------------------------------------------------------------------------
-- Los comentarios
-- --------------------------------------------------------------------------

COMMENT ON COLUMN pedidos.renglon.piezas_recibidas IS
    'Cuántas piezas llegaron, en total: lo dijo una persona (a mano) o la '
    'evidencia de SICAR que juzgó. De aquí sale recibido o recibido parcial, y '
    'cuánto faltó (ADR 0015). NULL si no se ha recibido.';

COMMENT ON COLUMN pedidos.renglon.piezas_que_faltaron IS
    'Piezas de un pedido anterior que llegó de menos y que este renglón trae de '
    'vuelta, ya sumadas a cantidad_propuesta. Son piezas, no ventas (ADR 0015). '
    'Casi siempre 0.';

COMMENT ON COLUMN pedidos.renglon.recibido_con_compras IS
    'Los compra_id de marts.fct_compras que sostienen la recepción -completa o '
    'parcial- (nunca el folio, de semántica no verificada). Una compra sostiene '
    'un solo renglón. NULL si no está recibido, o si se recibió a mano sin '
    'compra (ticket 27).';

COMMIT;


-- --------------------------------------------------------------------------
-- Qué quedó
-- --------------------------------------------------------------------------
--
-- Se imprime en vez de darse por hecho, igual que en las diez anteriores.

SELECT con.conrelid::regclass         AS tabla,
       con.conname                    AS restriccion,
       pg_get_constraintdef(con.oid)  AS definicion
  FROM pg_constraint con
 WHERE con.conname IN ('ck_renglon_piezas_recibidas',
                       'ck_renglon_completo_o_parcial',
                       'ck_renglon_piezas_que_faltaron')
 ORDER BY con.conname;

SELECT estado, count(*) AS renglones, count(piezas_recibidas) AS con_piezas
  FROM pedidos.renglon
 WHERE estado IN ('recibido', 'recibido parcial')
 GROUP BY estado
 ORDER BY estado;

\echo ''
\echo '>> COMPRUEBA ARRIBA: las tres restricciones, y que todo lo recibido tenga'
\echo '>> piezas. Sin esta migracion, la lista del dia no se puede leer con el'
\echo '>> codigo del ticket 27.'
\echo ''
\echo '>> sql/crear_rol.sql NO hace falta volver a correrlo: esta migracion no crea'
\echo '>> ninguna tabla y el permiso es sobre la tabla entera. Corre SI'
\echo '>> sql/verificar_rol.sql: sus comprobaciones 36 y 37 son nuevas.'
