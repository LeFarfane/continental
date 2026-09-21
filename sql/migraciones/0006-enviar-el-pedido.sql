-- 0006 - enviar un pedido: `borrador` -> `enviado`, firmado (ticket 21, ADR 0009).
--
-- NO CREA NINGUNA TABLA: el esquema `pedidos` sigue teniendo CINCO. Lo que hace
-- son tres cosas sobre `pedidos.pedido`:
--
--   1. Gana `enviado_por` y `enviado_en`: la firma de quien lo capturó.
--   2. `ck_pedido_estado` se amplía de `('borrador')` a `('borrador',
--      'enviado')`. **Es el precio que el ticket 20 dejó anotado con todas sus
--      letras** al negarse a adelantar un nombre que el glosario no tenía.
--   3. Entra `ck_pedido_envio`, que aparea el estado con la firma.
--
-- SE CORRE A MANO, UNA VEZ, CON CREDENCIALES DE DUEÑO, igual que
-- `sql/crear_tablas.sql` y las migraciones 0001 a 0005, y por la misma razón
-- (ADR 0003): esto es DDL, y el rol `continental` no puede hacer DDL a
-- propósito. **No lo corre el servicio, no lo corre una prueba y no lo corre el
-- lote de la noche.** Si algún día el código de arranque aplicara migraciones
-- solo, el rol necesitaría ALTER sobre sus tablas -- y con ALTER puede quitar un
-- CHECK, que es la mitad de las garantías de este esquema.
--
-- Desde `~/proyectos/Continental` en atlas -- **plano, no anidado**: en atlas los
-- repos son hermanos (`~/proyectos/Marlowe`, y `~/proyectos/Farmacia`, que es
-- farmacia-data), al revés que en la torre--:
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 \
--       < sql/migraciones/0006-enviar-el-pedido.sql
--
-- `<` y no `-f`: con `docker exec`, el `-f` de psql busca el archivo DENTRO del
-- contenedor, donde este repo no está montado. `ON_ERROR_STOP=1` porque sin él
-- psql sigue tras un error y termina diciendo que todo salió bien.
--
--
-- ## `sql/crear_rol.sql` NO hace falta volver a correrlo
--
-- Lo mismo que la 0005 y al revés que la 0003 y la 0004, que estrenaban una
-- TABLA: aquí solo se agregan columnas y se cambian restricciones, y el
-- `GRANT SELECT, INSERT, UPDATE` es sobre la tabla entera -- no se usan permisos
-- por columna, a propósito--.
--
-- Lo que SÍ conviene correr después es `sql/verificar_rol.sql`: sus
-- comprobaciones 27 y 28 son nuevas y leen DE VUELTA, desde el catálogo, que el
-- CHECK del estado conozca los dos valores y que la firma haya quedado pareada.
-- Las dos se pueden ver bien en este archivo y estar mal en la base.
--
--
-- ## QUÉ SIGNIFICA `enviado`, PORQUE LA PALABRA MIENTE
--
-- **Continental no le manda el pedido a ningún proveedor.** No entra a los
-- portales y no va a entrar: lo prohíbe la regla 1 de `CLAUDE.md` y el ADR 0002
-- dejó *capturar el pedido en el portal* fuera de alcance, con su razón -- cuatro
-- portales con carritos distintos, sesiones que se caen solas (las cuatro
-- caducadas el 2026-09-19), y un pedido capturado mal por un robot llega en
-- cajas--.
--
-- Lo que esta columna guarda es la **declaración de una persona**: *yo ya lo
-- capturé en el portal del proveedor*. Es un dato de otra naturaleza que todo lo
-- demás de este esquema -- una venta, un precio congelado, una existencia son
-- cosas que el sistema observó; esto no--, y de ahí salen las dos decisiones que
-- esta migración escribe en la tabla:
--
--   - **Firma y no acuse.** Un acuse es la respuesta de alguien más, y aquí no
--     hay alguien más: el hecho ocurrió en otra pantalla, con otras
--     credenciales. Lo único verdadero que se puede escribir es quién lo dice y
--     cuándo lo dijo. Es una FIRMA y NUNCA un permiso (regla 3 de CLAUDE.md).
--   - **Pareada con el estado.** Sin la mitad de ida, un pedido enviado no diría
--     quién -- y cuando la factura no cuadre no habrá a quién preguntarle qué se
--     capturó--. Sin la de vuelta, una firma colgada de un borrador diría que
--     alguien envió lo que nadie envió.
--
-- El ADR 0009 tiene el porqué entero, con las tres alternativas descartadas
-- (que Continental capture en el portal, que mande un correo, que no guarde
-- nada).
--
--
-- ## Lo que esta migración NO toca, y hace falta saberlo
--
-- `pedidos.renglon.estado` **no cambia**: `en tránsito` ya estaba en
-- `ck_renglon_estado` desde el ticket 07, con su acento, porque el glosario ya
-- lo tenía. Lo que cambia con el ticket 21 es que por fin **hay código que lo
-- escribe** (`almacenamiento._RENGLONES_A_TRANSITO`): hasta hoy solo lo
-- nombraban comentarios y pruebas.
--
-- Tampoco hace falta migrar dato alguno. `pedidos.pedido` está vacía en atlas y
-- es verificable, no una suposición: `sql/crear_tablas.sql` no se ha corrido
-- nunca ahí (ver `HANDOVER.md`). Aun así, la columna entra NULLable y el CHECK
-- se prueba contra lo que haya: cualquier fila que existiera es un borrador sin
-- firma, que es justo lo que `ck_pedido_envio` acepta.
--
--
-- ## Es idempotente
--
-- Correrlo dos veces no rompe nada y no cambia nada la segunda vez, igual que
-- las cinco anteriores y sin tabla de migraciones aplicadas: lo que protege es
-- que cada sentencia sea idempotente por sí misma. `ADD COLUMN IF NOT EXISTS`
-- para las columnas; `DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT` para las
-- restricciones, porque `ADD CONSTRAINT` no tiene `IF NOT EXISTS` en Postgres.
-- Quitar y volver a poner tiene además una propiedad que conviene: la
-- restricción que queda es la de este archivo, aunque alguien hubiera creado
-- otra con el mismo nombre y otra definición.
--
-- Quitar una restricción no borra una sola fila. Se hace con credenciales de
-- dueño y en una transacción: si el `ADD` fallara -- porque ya hay filas que la
-- violan-- el `DROP` se va con él y la tabla se queda como estaba.

SET client_encoding TO 'UTF8';

-- Que no lo corra quien no debe, igual que `crear_tablas.sql` y las cinco
-- migraciones anteriores. Con el rol acotado esto fallaría por permisos, pero el
-- mensaje de Postgres no diría cuál es la manera correcta de correrlo.
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
-- 1) `pedidos.pedido` gana la firma del envío
-- --------------------------------------------------------------------------
--
-- Las dos NULLables y sin DEFAULT. NULL aquí significa "todavía nadie lo ha
-- enviado", que es el estado de todo borrador, y un DEFAULT inventaría una
-- declaración que nadie hizo -- que es exactamente lo que la regla 4 de
-- CLAUDE.md prohíbe.
ALTER TABLE pedidos.pedido
    ADD COLUMN IF NOT EXISTS enviado_por text;

ALTER TABLE pedidos.pedido
    ADD COLUMN IF NOT EXISTS enviado_en timestamptz;

-- --------------------------------------------------------------------------
-- 2) `ck_pedido_estado` conoce los dos estados
-- --------------------------------------------------------------------------
--
-- El precio que el ticket 20 dejó anotado. Va ANTES de `ck_pedido_envio`
-- porque sin esto ninguna fila podría decir 'enviado' y el otro CHECK sería
-- vocabulario muerto.
--
-- SIN un estado de cancelado: nadie lo ha pedido, y un valor que ningún código
-- escribe invita a que alguien lo use con otro significado.
ALTER TABLE pedidos.pedido
    DROP CONSTRAINT IF EXISTS ck_pedido_estado;
ALTER TABLE pedidos.pedido
    ADD CONSTRAINT ck_pedido_estado
        CHECK (estado IN ('borrador', 'enviado'));

-- --------------------------------------------------------------------------
-- 3) La firma va pareada con el estado
-- --------------------------------------------------------------------------
--
-- La cadena vacía no existe en ninguna columna de texto de este esquema: se
-- compara igual que un dato y empareja con cualquier otra vacía. Sin encabezado
-- de Access, `web.app.quien()` devuelve 'sin-identificar', que SÍ es un dato.
ALTER TABLE pedidos.pedido
    DROP CONSTRAINT IF EXISTS ck_pedido_enviado_por;
ALTER TABLE pedidos.pedido
    ADD CONSTRAINT ck_pedido_enviado_por
        CHECK (enviado_por <> '');

-- ENVIADO SI Y SOLO SI HAY FIRMA Y HORA. El mismo par que
-- `ck_renglon_descarte`, `ck_renglon_ajuste` y `ck_renglon_eleccion`. Ver la
-- nota grande de la cabecera: lo que se guarda al enviar no es un hecho que
-- Continental haya observado, así que sin la firma no queda ningún hecho
-- guardado -- solo un "se envió" en voz pasiva.
ALTER TABLE pedidos.pedido
    DROP CONSTRAINT IF EXISTS ck_pedido_envio;
ALTER TABLE pedidos.pedido
    ADD CONSTRAINT ck_pedido_envio
        CHECK ((estado = 'enviado')
               = (enviado_por IS NOT NULL AND enviado_en IS NOT NULL));

-- --------------------------------------------------------------------------
-- Los comentarios
-- --------------------------------------------------------------------------

COMMENT ON COLUMN pedidos.pedido.estado IS
    'borrador o enviado. Nace en borrador y se puede modificar mientras esté '
    'así. enviado = una persona ya lo capturó en el portal del proveedor; '
    'Continental no le manda nada a nadie (ADR 0009).';

COMMENT ON COLUMN pedidos.pedido.enviado_por IS
    'Quién declaró haberlo capturado en el portal, según '
    'Cf-Access-Authenticated-User-Email. Es una FIRMA, no un permiso. NULL '
    'mientras siga en borrador.';

COMMENT ON COLUMN pedidos.pedido.enviado_en IS
    'Cuándo lo dijo, instante con zona. NULL mientras siga en borrador.';

COMMIT;


-- --------------------------------------------------------------------------
-- Qué quedó
-- --------------------------------------------------------------------------
--
-- Se imprime en vez de darse por hecho, igual que en las cinco anteriores: un
-- CHECK puede entrar con el acento deformado y verse impecable en el archivo.

SELECT a.attname                            AS columna,
       format_type(a.atttypid, a.atttypmod) AS tipo,
       NOT a.attnotnull                     AS admite_nulos
  FROM pg_attribute a
 WHERE a.attrelid = to_regclass('pedidos.pedido')
   AND a.attnum > 0
   AND NOT a.attisdropped
 ORDER BY a.attnum;

SELECT con.conname                   AS restriccion,
       pg_get_constraintdef(con.oid) AS definicion
  FROM pg_constraint con
 WHERE con.conrelid = to_regclass('pedidos.pedido')
 ORDER BY con.conname;

\echo ''
\echo '>> COMPRUEBA DOS COSAS ARRIBA, y las dos se pueden ver mal sin que nada falle:'
\echo '>>   1. ck_pedido_estado dice IN (borrador, enviado). Con el CHECK viejo, el'
\echo '>>      primer clic en Enviar rebota en atlas contra una violacion de'
\echo '>>      restriccion que el encargado va a ver como "algo fallo" (regla 5).'
\echo '>>   2. ck_pedido_envio aparea el estado con la firma en LOS DOS SENTIDOS.'
\echo '>>      Sin la mitad de ida, un pedido enviado puede no decir quien lo'
\echo '>>      capturo -- y enviado significa "yo ya lo capture en el portal", asi'
\echo '>>      que sin firma no queda ningun hecho guardado.'
\echo ''
\echo '>> sql/crear_rol.sql NO hace falta volver a correrlo: esta migracion no crea'
\echo '>> ninguna tabla y el GRANT es sobre la tabla entera. Corre SI'
\echo '>> sql/verificar_rol.sql: sus comprobaciones 27 y 28 son nuevas.'
