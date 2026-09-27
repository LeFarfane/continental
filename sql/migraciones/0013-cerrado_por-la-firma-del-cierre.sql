-- 0013 - cerrado_por, la firma del cierre (decision del dueño, 2026-09-27).
--
-- NO CREA NINGUNA TABLA: el esquema `pedidos` sigue teniendo CINCO. Lo que hace
-- es darle a `pedidos.pedido_sugerido` UNA columna y DOS CHECK:
--
--   - `cerrado_por` (text): quien cerro esta lista la ULTIMA vez. Admite
--     nulos y NO tiene DEFAULT.
--   - `ck_pedido_sugerido_cerrado_por`: la firma no va vacia.
--   - `ck_pedido_sugerido_cerrado_en_firmado`: si hay firma, tiene que haber
--     hora de cierre. (NO al reves: una fila cerrada antes de esta migracion
--     se queda con `cerrado_por = NULL` para siempre, y eso es valido.)
--
-- ## Para que
--
-- El dueño decidio que la lista de un dia se cierre SOLA en cuanto se arma la
-- de un dia posterior -"automatico, sin intervencion"-, para que las listas
-- vuelvan a ser cortas (un dia, no la ventana `2026-09-12 -> hoy` que llego a
-- 174 renglones) y para que las listas pasadas queden como bitacora navegable
-- en vez de vencerse sin poder reabrirse nunca. Un cierre automatico necesita
-- poder distinguirse de uno que hizo una persona con un clic -"¿por que dice
-- cerrada esta lista si nadie la cerro?" es la pregunta que alguien iba a
-- hacer-, y la respuesta es la misma que ya dio el ADR 0016 para reabrir:
-- una firma, guardada junto con la hora que ya existia.
--
-- `cerrado_por` vale un correo de Cloudflare Access para un clic humano, o el
-- literal `'sistema'` (`almacenamiento.SISTEMA`) cuando lo disparo abrir el
-- dia siguiente. Es una firma, no un permiso (regla 3 de CLAUDE.md): dice
-- quien lo hizo, no autoriza nada.
--
-- ## NO ROMPE EL CODIGO QUE HOY CORRE EN ATLAS
--
-- Se puede correr antes de desplegar sin que el servicio de hoy lo note, y es
-- a proposito:
--
--   - Ninguna sentencia del codigo viejo nombra esta columna. Su `INSERT` de
--     la lista no la escribe y queda en NULL: por eso NO es `NOT NULL` y NO
--     lleva DEFAULT.
--   - El CHECK de la firma no vacia acepta NULL, que es lo unico que el
--     codigo viejo deja.
--   - El CHECK pareado (`cerrado_por` -> `cerrado_en`) NO exige lo contrario:
--     un `_CERRAR` viejo que ponga `cerrado_en` sin `cerrado_por` sigue
--     pasando, porque `cerrado_por` se queda en NULL.
--   - No toca `pedidos.renglon` ni `pedidos.pedido`.
--
-- ## HAY QUE CORRERLA ANTES DE DESPLEGAR EL CODIGO DE ESTE TICKET
--
-- No es opcional: `_LEER_LISTA`, `_LEER_LISTA_POR_ID`, `_INSERTAR_LISTA`,
-- `_CERRAR`, `_REABRIR` y `_CERRAR_LAS_DE_DIAS_ANTERIORES` DEVUELVEN la
-- columna nueva, asi que con el codigo nuevo y la base vieja la lista del dia
-- no se puede leer ni armar -- "column cerrado_por does not exist"-- y la
-- pantalla se queda en "no se pudo armar el pedido sugerido". El lote de la
-- noche tambien se corta. La comprobacion nueva de `verificar_rol.sql` lo caza.
--
--
-- SE CORRE A MANO, UNA VEZ, CON CREDENCIALES DE DUEÑO, igual que
-- `sql/crear_tablas.sql` y las migraciones 0001 a 0012, y por la misma razon
-- (ADR 0003): esto es DDL, y el rol `continental` no puede hacer DDL a
-- proposito. **No lo corre el servicio, no lo corre una prueba y no lo corre el
-- lote de la noche.**
--
-- Desde `~/proyectos/Continental` en atlas -- **plano, no anidado**--:
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 \
--       < sql/migraciones/0013-cerrado_por-la-firma-del-cierre.sql
--
-- `<` y no `-f`: con `docker exec`, el `-f` de psql busca el archivo DENTRO del
-- contenedor, donde este repo no esta montado. `ON_ERROR_STOP=1` porque sin el
-- psql sigue tras un error y termina diciendo que todo salio bien.
--
--
-- ## `sql/crear_rol.sql` NO hace falta volver a correrlo
--
-- Igual que la 0005 a la 0012: aqui solo se agrega una columna y dos CHECK, y
-- el `GRANT SELECT, INSERT, UPDATE` es sobre la tabla entera -- no se usan
-- permisos por columna, a proposito--. Cerrar es un `UPDATE`, que el rol ya
-- tiene sobre `pedido_sugerido` desde el ticket 07.
--
-- Lo que SI conviene correr despues es `sql/verificar_rol.sql`: tiene una
-- comprobacion nueva.
--
-- ## Sin relleno
--
-- Ninguna lista guarda hoy quien la cerro -ningun codigo lo hacia-, asi que
-- NULL es la verdad de toda fila existente, cerrada o no.
--
-- ## Es idempotente
--
-- Correrla dos veces no rompe nada y no cambia nada la segunda vez, igual que
-- las doce anteriores: `ADD COLUMN IF NOT EXISTS` y `DROP CONSTRAINT IF EXISTS`
-- antes de cada `ADD CONSTRAINT`, todo en una transaccion.

SET client_encoding TO 'UTF8';

-- Que no lo corra quien no debe, igual que las doce anteriores.
DO $guardia$
BEGIN
    IF current_user = 'continental' THEN
        RAISE EXCEPTION '%',
            'Esta migracion se corre con credenciales de DUEÑO (usuario '
            || 'farmacia), no con el rol acotado continental: el rol no tiene '
            || 'ALTER sobre sus tablas y eso es deliberado (ADR 0003).';
    END IF;
END
$guardia$;

BEGIN;

-- --------------------------------------------------------------------------
-- `pedidos.pedido_sugerido` gana la firma del cierre
-- --------------------------------------------------------------------------
ALTER TABLE pedidos.pedido_sugerido
    ADD COLUMN IF NOT EXISTS cerrado_por text;

ALTER TABLE pedidos.pedido_sugerido
    DROP CONSTRAINT IF EXISTS ck_pedido_sugerido_cerrado_por;
ALTER TABLE pedidos.pedido_sugerido
    ADD CONSTRAINT ck_pedido_sugerido_cerrado_por
        CHECK (cerrado_por <> '');

ALTER TABLE pedidos.pedido_sugerido
    DROP CONSTRAINT IF EXISTS ck_pedido_sugerido_cerrado_en_firmado;
ALTER TABLE pedidos.pedido_sugerido
    ADD CONSTRAINT ck_pedido_sugerido_cerrado_en_firmado
        CHECK (cerrado_por IS NULL OR cerrado_en IS NOT NULL);

COMMENT ON COLUMN pedidos.pedido_sugerido.cerrado_por IS
    'Quien cerro esta lista la ULTIMA vez (correo de Cloudflare Access, o '
    '''sistema'' si lo disparo abrir el dia siguiente): firma, no permiso. '
    'NULL si sigue abierta, o si se cerro antes de esta migracion.';

COMMIT;


-- --------------------------------------------------------------------------
-- Que quedo
-- --------------------------------------------------------------------------
--
-- Se imprime en vez de darse por hecho, igual que en las doce anteriores.

SELECT a.attname                            AS columna,
       format_type(a.atttypid, a.atttypmod) AS tipo,
       NOT a.attnotnull                     AS admite_nulos
  FROM pg_attribute a
 WHERE a.attrelid = to_regclass('pedidos.pedido_sugerido')
   AND a.attname = 'cerrado_por'
   AND NOT a.attisdropped;

SELECT con.conname                    AS restriccion,
       pg_get_constraintdef(con.oid)  AS definicion
  FROM pg_constraint con
 WHERE con.conrelid = to_regclass('pedidos.pedido_sugerido')
   AND con.conname IN ('ck_pedido_sugerido_cerrado_por',
                       'ck_pedido_sugerido_cerrado_en_firmado')
 ORDER BY con.conname;

\echo ''
\echo '>> COMPRUEBA ARRIBA: una columna que admite nulos y dos restricciones.'
\echo '>> Sin esta migracion, la lista del dia no se puede leer con el codigo'
\echo '>> de este ticket (2026-09-27). El codigo de antes no la nota: se puede'
\echo '>> correr primero.'
\echo ''
\echo '>> sql/crear_rol.sql NO hace falta volver a correrlo: esta migracion no'
\echo '>> crea ninguna tabla y el permiso es sobre la tabla entera. Corre SI'
\echo '>> sql/verificar_rol.sql: tiene una comprobacion nueva.'
