-- 0009 - cancelar un pedido y devolver a la lista lo atrasado (ticket 25, ADR 0013).
--
-- NO CREA NINGUNA TABLA: el esquema `pedidos` sigue teniendo CINCO. Lo que hace:
--
--   - `pedidos.pedido` gana el estado `cancelado` y su firma (`cancelado_por`,
--     `cancelado_en`), y `ck_pedido_envio` pasa a exigir la firma del envío
--     también en un pedido cancelado -- solo se cancela lo que alguien dijo
--     haber enviado, y esa palabra no se borra--.
--   - `pedidos.renglon` gana el estado `cancelado` y la misma firma.
--
-- ## Para qué
--
-- Desde el ticket 24 un renglón `en tránsito` no se vuelve a proponer. Si nunca
-- llega -- el pedido nunca se capturó en el portal, o el proveedor no lo
-- surtió--, se quedaría fuera de la lista PARA SIEMPRE. Esta migración es lo que
-- la válvula de escape necesita de la tabla:
--
--   - CANCELAR un pedido `enviado`: una persona dice que NO está en el portal.
--     El pedido y sus renglones en tránsito pasan a `cancelado`, firmados.
--   - DEVOLVER A LA LISTA un renglón atrasado -- más de N días en camino, N en
--     `config/continental.yml`--, él solo: pasa a `cancelado`, firmado, y su
--     pedido sigue `enviado`.
--
-- En los dos casos lo que vuelve es el PRODUCTO, en la siguiente lista, con
-- todo lo que el renglón cubría. El renglón NO vuelve a `abierto`: su lista casi
-- siempre está cerrada, y el glosario dice que solo una lista abierta se deja
-- modificar. El ADR 0013 tiene el porqué, y dice en qué punto enmienda al 0009
-- (que negó "desenviar", y lo sigue negando: `cancelado` es un final).
--
-- "Atrasado" NO es un estado y NO está en ningún CHECK: se calcula cada vez
-- contra el instante del envío. No se llama "vencido", que es de la lista.
--
--
-- SE CORRE A MANO, UNA VEZ, CON CREDENCIALES DE DUEÑO, igual que
-- `sql/crear_tablas.sql` y las migraciones 0001 a 0008, y por la misma razón
-- (ADR 0003): esto es DDL, y el rol `continental` no puede hacer DDL a
-- propósito. **No lo corre el servicio, no lo corre una prueba y no lo corre el
-- lote de la noche.**
--
-- Desde `~/proyectos/Continental` en atlas -- **plano, no anidado**--:
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 \
--       < sql/migraciones/0009-cancelar-y-devolver-lo-atrasado.sql
--
-- `<` y no `-f`: con `docker exec`, el `-f` de psql busca el archivo DENTRO del
-- contenedor, donde este repo no está montado. `ON_ERROR_STOP=1` porque sin él
-- psql sigue tras un error y termina diciendo que todo salió bien.
--
--
-- ## HAY QUE CORRERLA ANTES DE DESPLEGAR EL CÓDIGO DEL TICKET 25
--
-- No es opcional: `_LEER_RENGLONES`, `_LEER_RENGLON_POR_ID`, `_LEER_PEDIDOS` y
-- `_LO_YA_PEDIDO` NOMBRAN las columnas nuevas, así que con el código nuevo y la
-- base vieja **la lista del día no se puede leer ni armar** -- "column
-- cancelado_por does not exist"-- y la pantalla entera se queda en "no se pudo
-- armar el pedido sugerido". El lote de la noche también se corta. Es lo mismo
-- que pasó con la 0005 a la 0008. Las comprobaciones 31 a 33 de
-- `verificar_rol.sql` lo cazan.
--
--
-- ## `sql/crear_rol.sql` NO hace falta volver a correrlo
--
-- Igual que la 0005 a la 0008, y al revés que la 0003 y la 0004, que estrenaban
-- una TABLA: aquí solo se agregan columnas y se cambian CHECK, y el `GRANT
-- SELECT, INSERT, UPDATE` es sobre la tabla entera -- no se usan permisos por
-- columna, a propósito--. Cancelar y devolver son `UPDATE`, que el rol ya tiene
-- sobre `pedido` y `renglon` desde el ticket 07.
--
-- Lo que SÍ conviene correr después es `sql/verificar_rol.sql`: sus
-- comprobaciones 31, 32 y 33 son nuevas.
--
--
-- ## Por qué se reemplazan los CHECK y no se agregan otros
--
-- `ck_pedido_estado`, `ck_renglon_estado` y `ck_pedido_envio` ya existían, y un
-- CHECK nuevo al lado del viejo no amplía nada: los dos se tendrían que cumplir
-- y el viejo seguiría rechazando 'cancelado'. Se tiran y se vuelven a crear con
-- el MISMO nombre, que es el que citan los mensajes de `almacenamiento.py` y las
-- comprobaciones de `verificar_rol.sql`.
--
-- ## Es idempotente
--
-- Correrla dos veces no rompe nada y no cambia nada la segunda vez, igual que
-- las ocho anteriores: `ADD COLUMN IF NOT EXISTS` y `DROP CONSTRAINT IF EXISTS`
-- antes de cada `ADD CONSTRAINT`, todo en una transacción.

SET client_encoding TO 'UTF8';

-- Que no lo corra quien no debe, igual que las ocho anteriores.
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
-- 1) El pedido: el estado `cancelado` y su firma
-- --------------------------------------------------------------------------
ALTER TABLE pedidos.pedido
    ADD COLUMN IF NOT EXISTS cancelado_por text;
ALTER TABLE pedidos.pedido
    ADD COLUMN IF NOT EXISTS cancelado_en timestamptz;

ALTER TABLE pedidos.pedido
    DROP CONSTRAINT IF EXISTS ck_pedido_estado;
ALTER TABLE pedidos.pedido
    ADD CONSTRAINT ck_pedido_estado
        CHECK (estado IN ('borrador', 'enviado', 'cancelado'));

-- La firma del envío se queda en un pedido cancelado: alguien SÍ dijo haberlo
-- capturado, y esa palabra es parte de su historia.
ALTER TABLE pedidos.pedido
    DROP CONSTRAINT IF EXISTS ck_pedido_envio;
ALTER TABLE pedidos.pedido
    ADD CONSTRAINT ck_pedido_envio
        CHECK ((estado IN ('enviado', 'cancelado'))
               = (enviado_por IS NOT NULL AND enviado_en IS NOT NULL));

ALTER TABLE pedidos.pedido
    DROP CONSTRAINT IF EXISTS ck_pedido_cancelado_por;
ALTER TABLE pedidos.pedido
    ADD CONSTRAINT ck_pedido_cancelado_por
        CHECK (cancelado_por <> '');

ALTER TABLE pedidos.pedido
    DROP CONSTRAINT IF EXISTS ck_pedido_cancelacion;
ALTER TABLE pedidos.pedido
    ADD CONSTRAINT ck_pedido_cancelacion
        CHECK ((estado = 'cancelado')
               = (cancelado_por IS NOT NULL AND cancelado_en IS NOT NULL));

-- --------------------------------------------------------------------------
-- 2) El renglón: el estado `cancelado` y su firma
-- --------------------------------------------------------------------------
ALTER TABLE pedidos.renglon
    ADD COLUMN IF NOT EXISTS cancelado_por text;
ALTER TABLE pedidos.renglon
    ADD COLUMN IF NOT EXISTS cancelado_en timestamptz;

-- 'en tránsito' CON ACENTO. Si psql manda este archivo como latin1 el acento
-- entra deformado DENTRO del CHECK; por eso el `SET client_encoding` de arriba,
-- y por eso la comprobación 15 de `verificar_rol.sql` lo vuelve a leer.
ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_estado;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_estado
        CHECK (estado IN ('abierto', 'en tránsito', 'recibido',
                          'recibido parcial', 'descartado', 'cancelado'));

ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_cancelado_por;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_cancelado_por
        CHECK (cancelado_por <> '');

ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_cancelacion;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_cancelacion
        CHECK ((estado = 'cancelado')
               = (cancelado_por IS NOT NULL AND cancelado_en IS NOT NULL));

-- --------------------------------------------------------------------------
-- Los comentarios
-- --------------------------------------------------------------------------

COMMENT ON COLUMN pedidos.pedido.estado IS
    'borrador, enviado o cancelado. Nace en borrador y se puede modificar '
    'mientras esté así. enviado = una persona ya lo capturó en el portal del '
    'proveedor; Continental no le manda nada a nadie (ADR 0009). cancelado = '
    'una persona dijo que no está en el portal; es un final (ADR 0013).';

COMMENT ON COLUMN pedidos.pedido.cancelado_por IS
    'Quién dijo que el pedido no está en el portal del proveedor (nunca se '
    'capturó, o se canceló allá). Es una FIRMA, no un permiso. NULL si no '
    'está cancelado.';

COMMENT ON COLUMN pedidos.pedido.cancelado_en IS
    'Cuándo lo dijo, instante con zona. NULL si no está cancelado.';

COMMENT ON COLUMN pedidos.renglon.estado IS
    'abierto | en tránsito | recibido | recibido parcial | descartado | '
    'cancelado. Con acento en "en tránsito": el glosario de CONTEXT.md manda '
    'sobre el nombre de cualquier cosa.';

COMMENT ON COLUMN pedidos.renglon.cancelado_por IS
    'Quién lo dejó de esperar: canceló su pedido, o lo devolvió a la lista por '
    'atrasado (ADR 0013). Es una FIRMA, no un permiso. NULL si no está '
    'cancelado.';

COMMENT ON COLUMN pedidos.renglon.cancelado_en IS
    'Cuándo, instante con zona. NULL si no está cancelado.';

COMMIT;


-- --------------------------------------------------------------------------
-- Qué quedó
-- --------------------------------------------------------------------------
--
-- Se imprime en vez de darse por hecho, igual que en las ocho anteriores: un
-- CHECK puede entrar con el acento deformado y verse impecable en el archivo.

SELECT con.conrelid::regclass         AS tabla,
       con.conname                    AS restriccion,
       pg_get_constraintdef(con.oid)  AS definicion
  FROM pg_constraint con
 WHERE con.conname IN ('ck_pedido_estado', 'ck_pedido_envio',
                       'ck_pedido_cancelacion', 'ck_renglon_estado',
                       'ck_renglon_cancelacion')
 ORDER BY con.conname;

\echo ''
\echo '>> COMPRUEBA ARRIBA: ck_pedido_estado con borrador, enviado y cancelado;'
\echo '>> ck_renglon_estado con los seis y en transito CON ACENTO; y las dos'
\echo '>> ck_..._cancelacion pareando el estado con la firma. Sin esta migracion,'
\echo '>> la lista del dia no se puede leer con el codigo del ticket 25.'
\echo ''
\echo '>> sql/crear_rol.sql NO hace falta volver a correrlo: esta migracion no crea'
\echo '>> ninguna tabla y el GRANT es sobre la tabla entera. Corre SI'
\echo '>> sql/verificar_rol.sql: sus comprobaciones 31, 32 y 33 son nuevas.'
