-- 0008 - el renglón que vuelve dice desde cuándo cuenta sus ventas (ticket 24, ADR 0012).
--
-- NO CREA NINGUNA TABLA: el esquema `pedidos` sigue teniendo CINCO. Lo único que
-- hace es darle a `pedidos.renglon` una columna, `ventas_desde`, de tipo `date`
-- y que admite nulos.
--
-- ## Para qué
--
-- Un renglón `en tránsito` no se vuelve a proponer, y lo que se vende de ese
-- producto mientras viene en camino se queda en `marts.fct_ventas` sin copiarse
-- a ninguna parte. Cuando el renglón se cierra -- `recibido` o `recibido
-- parcial`, los tickets 26 y 27--, la siguiente lista cuenta ese producto
-- DESDE EL DÍA SIGUIENTE AL QUE REPUSO SU PEDIDO, aunque el corte haya avanzado
-- encima. Ese día casi nunca es el principio de la lista, y el renglón lo dice
-- aquí: sin esto, "pide 4" en una lista de un solo día con una sola venta no se
-- podría verificar mirando la pantalla, y "se vendieron tres, se piden tres" es
-- lo que hace defendible la reposición 1 a 1 (ADR 0002).
--
-- NULL -- el caso de casi todos-- es "desde el principio de la lista"
-- (`ventas_consideradas_desde`). Es la verdad de todo renglón que exista hoy,
-- así que no hace falta migrar dato alguno y no lleva DEFAULT.
--
-- ## Sin CHECK, y a propósito
--
-- La regla que relaciona esta columna con algo -- "es distinta del principio de
-- la ventana de SU lista"-- mira otra tabla, y un CHECK no puede mirar otra
-- fila. La asegura el código que la escribe (`transito.MemoriaDeLoPedido`), con
-- sus pruebas.
--
--
-- SE CORRE A MANO, UNA VEZ, CON CREDENCIALES DE DUEÑO, igual que
-- `sql/crear_tablas.sql` y las migraciones 0001 a 0007, y por la misma razón
-- (ADR 0003): esto es DDL, y el rol `continental` no puede hacer DDL a
-- propósito. **No lo corre el servicio, no lo corre una prueba y no lo corre el
-- lote de la noche.**
--
-- Desde `~/proyectos/Continental` en atlas -- **plano, no anidado**--:
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 \
--       < sql/migraciones/0008-el-renglon-que-vuelve-dice-desde-cuando.sql
--
-- `<` y no `-f`: con `docker exec`, el `-f` de psql busca el archivo DENTRO del
-- contenedor, donde este repo no está montado. `ON_ERROR_STOP=1` porque sin él
-- psql sigue tras un error y termina diciendo que todo salió bien.
--
--
-- ## HAY QUE CORRERLA ANTES DE DESPLEGAR EL CÓDIGO DEL TICKET 24
--
-- No es opcional: `_LEER_RENGLONES`, `_LEER_RENGLON_POR_ID`,
-- `_INSERTAR_RENGLONES` y `_LO_YA_PEDIDO` NOMBRAN la columna nueva, así que con
-- el código nuevo y la base vieja **la lista del día no se puede leer ni
-- armar** -- "column ventas_desde does not exist"-- y la pantalla entera se
-- queda en "no se pudo armar el pedido sugerido". Es lo mismo que pasó con la
-- 0005, la 0006 y la 0007. El lote de la noche también se corta, con su motivo
-- en el journal. La comprobación 30 de `verificar_rol.sql` lo caza.
--
--
-- ## `sql/crear_rol.sql` NO hace falta volver a correrlo
--
-- Igual que la 0005, la 0006 y la 0007, y al revés que la 0003 y la 0004, que
-- estrenaban una TABLA: aquí solo se agrega una columna, y el `GRANT SELECT,
-- INSERT, UPDATE` es sobre la tabla entera -- no se usan permisos por columna,
-- a propósito--. `_LO_YA_PEDIDO` lee `renglon`, `pedido_sugerido` y `pedido`,
-- las tres con `SELECT` desde el ticket 07.
--
-- Lo que SÍ conviene correr después es `sql/verificar_rol.sql`: su comprobación
-- 30 es nueva y lee DE VUELTA, desde el catálogo, que la columna esté y sea
-- `date` que admite nulos.
--
--
-- ## POR QUÉ UNA COLUMNA Y NO UNA TABLA DE VENTAS RETENIDAS
--
-- Es la decisión cara del ticket y está entera en el ADR 0012. En corto: la
-- venta ya está guardada en `marts.fct_ventas` y copiarla la duplicaría; una
-- copia tomada al excluir el producto no vería las ventas que llegan tarde (el
-- sábado llega el lunes en la noche); y una tabla nueva obligaría a volver a
-- correr `crear_rol.sql`, que es el paso que más se olvida. Lo único que no
-- existía era que el renglón que vuelve DIJERA desde cuándo cuenta.
--
-- ## Es idempotente
--
-- Correrla dos veces no rompe nada y no cambia nada la segunda vez, igual que
-- las siete anteriores: `ADD COLUMN IF NOT EXISTS`, en una transacción.

SET client_encoding TO 'UTF8';

-- Que no lo corra quien no debe, igual que las siete anteriores.
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
-- `pedidos.renglon` gana su ventana propia
-- --------------------------------------------------------------------------
ALTER TABLE pedidos.renglon
    ADD COLUMN IF NOT EXISTS ventas_desde date;

COMMENT ON COLUMN pedidos.renglon.ventas_desde IS
    'Desde qué día se sumaron las ventas de este renglón cuando no es el '
    'principio de la ventana de su lista: el producto venía en camino y ya '
    'llegó (ADR 0012). NULL = desde ventas_consideradas_desde de su lista.';

COMMIT;


-- --------------------------------------------------------------------------
-- Qué quedó
-- --------------------------------------------------------------------------
--
-- Se imprime en vez de darse por hecho, igual que en las siete anteriores.

SELECT a.attname                            AS columna,
       format_type(a.atttypid, a.atttypmod) AS tipo,
       NOT a.attnotnull                     AS admite_nulos
  FROM pg_attribute a
 WHERE a.attrelid = to_regclass('pedidos.renglon')
   AND a.attname = 'ventas_desde'
   AND NOT a.attisdropped;

\echo ''
\echo '>> COMPRUEBA ARRIBA una columna: ventas_desde, date, admite nulos. Si falta,'
\echo '>> la lista del dia no se puede leer con el codigo del ticket 24.'
\echo ''
\echo '>> sql/crear_rol.sql NO hace falta volver a correrlo: esta migracion no crea'
\echo '>> ninguna tabla y el GRANT es sobre la tabla entera. Corre SI'
\echo '>> sql/verificar_rol.sql: su comprobacion 30 es nueva.'
