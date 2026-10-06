-- 0020 - lo que espera conserva su proveedor y dice desde cuándo (lista de
-- espera, ticket 04; enmienda del 2026-10-05 al ADR 0025).
--
-- NO CREA NINGUNA TABLA: el esquema `pedidos` sigue teniendo SIETE. Lo que hace
-- es darle a `pedidos.renglon` tres columnas y cuatro CHECK:
--
--   - `proveedor_de_la_espera`: a quién se le iba a pedir cuando una persona
--     mandó el renglón a espera. El del pedido al que estaba repartido; si no
--     estaba repartido, el que se eligió a mano; si no hay ninguno, NULL y la
--     lista siguiente lo reparte como hoy. Es la clave de Doyle, la misma
--     columna de texto que `pedido.proveedor` y `renglon.proveedor_elegido`;
--   - `espera_desde`: la FECHA de la lista donde se mandó por primera vez. Es la
--     que se arrastra: volver a mandar a espera algo que ya venía de la espera
--     no la mueve, y por eso es una fecha y no un instante;
--   - `listas_en_espera`: cuántas listas lleva esperando, desde 1. La espera no
--     tiene tope de veces, pero el contador está a la vista (historia 27 del
--     spec) para que alguien decida cuando algo lleva demasiado.
--
-- ## Qué relacionan los CHECK
--
--   - `ck_renglon_espera_proveedor`: el proveedor no es la cadena vacía. O hay
--     clave o es NULL, igual que `pospuesto_por`.
--   - `ck_renglon_espera_listas`: el contador es al menos 1.
--   - `ck_renglon_espera`: la fecha y el contador van JUNTOS o ninguno. Una
--     fecha sin contador, o al revés, no dice desde cuándo espera ni cuántas
--     listas lleva.
--   - `ck_renglon_espera_pospuesto`: un renglón `pospuesto` siempre trae fecha y
--     contador. **Al revés NO**: un renglón `abierto` puede traerlos, porque la
--     lista siguiente (ticket 05) los copia al renglón nuevo que nace de lo que
--     esperaba, y ahí siguen siendo verdad. Lo único que NO se relaciona es el
--     proveedor con el estado: un abierto que viene de la espera lo conserva por
--     la misma razón, y un pospuesto sin proveedor es "no se había repartido".
--
-- ## Lo que se rellena
--
-- Los renglones que YA estén `pospuesto` cuando se corre esto (de la 0019, antes
-- de la lista de espera) no tenían estas columnas, y `ck_renglon_espera_
-- pospuesto` los rechazaría. Se les pone lo que MANDAR A ESPERA les habría
-- puesto: proveedor del pedido, o el elegido, o NULL; desde la fecha de su
-- lista; una lista. **No se les quita el pedido**: lo hará el código nuevo al
-- mandar a espera, y un renglón pospuesto de antes se ve igual de bien dentro
-- de su pedido hasta que su lista se cierre. Ningún otro renglón se toca.
--
--
-- SE CORRE A MANO, UNA VEZ, CON CREDENCIALES DE DUEÑO, igual que
-- `sql/crear_tablas.sql` y las migraciones 0001 a 0019, y por la misma razón
-- (ADR 0003): esto es DDL, y el rol `continental` no puede hacer DDL a
-- propósito. **No lo corre el servicio, no lo corre una prueba y no lo corre el
-- lote de la noche.**
--
-- Desde `~/proyectos/Continental` en atlas -- **plano, no anidado**--:
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 \
--       < sql/migraciones/0020-la-espera-con-proveedor-y-edad.sql
--
-- `<` y no `-f`: con `docker exec`, el `-f` de psql busca el archivo DENTRO del
-- contenedor, donde este repo no está montado. `ON_ERROR_STOP=1` porque sin él
-- psql sigue tras un error y termina diciendo que todo salió bien.
--
--
-- ## HAY QUE CORRERLA ANTES DE DESPLEGAR EL CÓDIGO DE LA LISTA DE ESPERA
--
-- No es opcional: `_LEER_RENGLONES`, `_LEER_RENGLON_POR_ID` y `_LO_POSPUESTO`
-- NOMBRAN las columnas nuevas y `_POSPONER` las escribe, así que con el código
-- nuevo y la base vieja la lista del día no se puede leer -- "column
-- proveedor_de_la_espera does not exist"-- y el lote de la noche se corta. Es lo
-- mismo que pasó con la 0005 a la 0019. `verificar --forma` detiene el
-- despliegue (paso 4 de `desplegar.sh`, ADR 0017) y nombra este archivo: las
-- tres columnas nuevas son las testigo.
--
--
-- ## `sql/crear_rol.sql` NO hace falta volver a correrlo
--
-- Aquí solo se agregan columnas y CHECK, y el `GRANT SELECT, INSERT, UPDATE` es
-- sobre la tabla entera -- no se usan permisos por columna, a propósito--.
-- Mandar a espera y sacar de la espera son `UPDATE`, que el rol ya tiene sobre
-- `renglon`. De `marts` no se lee nada nuevo (regla 6 de `CLAUDE.md`).
--
-- ## Es idempotente
--
-- Correrla dos veces no rompe nada y no cambia nada la segunda vez, igual que
-- las anteriores: `ADD COLUMN IF NOT EXISTS`, el relleno solo toca lo que aún no
-- tiene fecha, y `DROP CONSTRAINT IF EXISTS` antes de cada `ADD CONSTRAINT`,
-- todo en una transacción.

SET client_encoding TO 'UTF8';

-- Que no lo corra quien no debe, igual que las anteriores.
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
-- 1) Las tres columnas
-- --------------------------------------------------------------------------
ALTER TABLE pedidos.renglon
    ADD COLUMN IF NOT EXISTS proveedor_de_la_espera text;
ALTER TABLE pedidos.renglon
    ADD COLUMN IF NOT EXISTS espera_desde date;
ALTER TABLE pedidos.renglon
    ADD COLUMN IF NOT EXISTS listas_en_espera integer;

-- --------------------------------------------------------------------------
-- 2) Lo que ya estaba pospuesto
-- --------------------------------------------------------------------------
UPDATE pedidos.renglon AS r
   SET proveedor_de_la_espera = coalesce(
           (SELECT pe.proveedor
              FROM pedidos.pedido AS pe
             WHERE pe.pedido_id = r.pedido_id
               AND pe.negocio = r.negocio),
           r.proveedor_elegido),
       espera_desde = s.fecha_del_pedido,
       listas_en_espera = 1
  FROM pedidos.pedido_sugerido AS s
 WHERE r.estado = 'pospuesto'
   AND r.espera_desde IS NULL
   AND s.pedido_sugerido_id = r.pedido_sugerido_id
   AND s.negocio = r.negocio;

-- --------------------------------------------------------------------------
-- 3) Los CHECK
-- --------------------------------------------------------------------------
ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_espera_proveedor;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_espera_proveedor
        CHECK (proveedor_de_la_espera <> '');

ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_espera_listas;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_espera_listas
        CHECK (listas_en_espera >= 1);

ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_espera;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_espera
        CHECK ((espera_desde IS NULL) = (listas_en_espera IS NULL));

ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_espera_pospuesto;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_espera_pospuesto
        CHECK (estado <> 'pospuesto' OR espera_desde IS NOT NULL);

-- --------------------------------------------------------------------------
-- Los comentarios
-- --------------------------------------------------------------------------

COMMENT ON COLUMN pedidos.renglon.proveedor_de_la_espera IS
    'A quién se le iba a pedir cuando el renglón se mandó a espera: el del '
    'pedido al que estaba repartido, y si no, el elegido a mano (clave de '
    'Doyle). NULL = no tenía ninguno y la lista siguiente lo reparte.';

COMMENT ON COLUMN pedidos.renglon.espera_desde IS
    'Fecha de la lista donde el renglón se mandó a espera POR PRIMERA VEZ; se '
    'arrastra al volver a mandarlo. NULL si nunca ha esperado.';

COMMENT ON COLUMN pedidos.renglon.listas_en_espera IS
    'Cuántas listas lleva esperando (>= 1), junto con espera_desde. Sin tope: '
    'está a la vista para que alguien decida cuando algo lleva demasiado. NULL '
    'si nunca ha esperado.';

COMMIT;


-- --------------------------------------------------------------------------
-- Qué quedó
-- --------------------------------------------------------------------------
--
-- Se imprime en vez de darse por hecho, igual que en las anteriores.

SELECT con.conrelid::regclass         AS tabla,
       con.conname                    AS restriccion,
       pg_get_constraintdef(con.oid)  AS definicion
  FROM pg_constraint con
 WHERE con.conname IN ('ck_renglon_espera_proveedor',
                       'ck_renglon_espera_listas',
                       'ck_renglon_espera',
                       'ck_renglon_espera_pospuesto')
 ORDER BY con.conname;

SELECT estado,
       count(*)                                   AS renglones,
       count(espera_desde)                        AS con_espera,
       count(proveedor_de_la_espera)              AS con_proveedor
  FROM pedidos.renglon
 GROUP BY estado
 ORDER BY estado;

\echo ''
\echo '>> COMPRUEBA ARRIBA: las cuatro restricciones, y que todo renglon pospuesto'
\echo '>> tenga con_espera igual a renglones. Sin esta migracion, la lista del dia'
\echo '>> no se puede leer con el codigo de la lista de espera.'
\echo ''
\echo '>> sql/crear_rol.sql NO hace falta volver a correrlo: esta migracion no crea'
\echo '>> ninguna tabla y el permiso es sobre la tabla entera.'
