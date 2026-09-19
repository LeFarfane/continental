-- 0002 - `pedidos.renglon` gana `cantidad_final`, `ajustada_por` y
-- `ajustada_en` (ticket 11).
--
-- SE CORRE A MANO, UNA VEZ, CON CREDENCIALES DE DUEÑO, igual que
-- `sql/crear_tablas.sql` y la migración 0001, y por la misma razón (ADR 0003):
-- esto es DDL, y el rol `continental` no puede hacer DDL a propósito. **No lo
-- corre el servicio, no lo corre una prueba y no lo corre el lote de la
-- noche.** Si algún día el código de arranque aplica migraciones solo, el rol
-- necesitaría ALTER sobre sus tablas -- y con ALTER puede quitar un CHECK, que
-- es la mitad de las garantías de este esquema.
--
-- Desde `~/proyectos/Continental` en atlas:
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 \
--       < sql/migraciones/0002-renglon-cantidad-final-y-quien-la-ajusto.sql
--
-- `<` y no `-f`: con `docker exec`, el `-f` de psql busca el archivo DENTRO
-- del contenedor, donde este repo no está montado. `ON_ERROR_STOP=1` porque
-- sin él psql sigue tras un error y termina diciendo que todo salió bien.
--
-- **Va después de la 0001**, aunque no dependa de sus columnas: las dos son
-- idempotentes y el orden solo importa para que el estado de la tabla se pueda
-- contar como una historia. `sql/crear_rol.sql` NO hace falta volver a
-- correrlo: el `GRANT SELECT, INSERT, UPDATE` es sobre la tabla entera y cubre
-- las columnas nuevas (no se usan permisos por columna, a propósito).
--
--
-- ## Qué guarda, y por qué son tres columnas y no una
--
-- El encargado sabe cosas que el sistema no -que mañana es puente, que un
-- cliente viene por una caja entera- y corrige la cantidad antes de pedir.
-- Esa corrección se guarda **al lado** de la propuesta del sistema, nunca
-- encima:
--
-- - `cantidad_propuesta` ya existía y **es inmutable**. Ninguna sentencia de
--   Continental la nombra en un SET; se escribe una sola vez, en el INSERT que
--   arma la lista.
-- - `cantidad_final` es lo que la persona decidió pedir. NULL = nadie la tocó.
-- - `ajustada_por` y `ajustada_en` son la firma de esa decisión, con el mismo
--   criterio que `descartado_por` / `descartado_en` del ticket 10.
--
-- La diferencia entre las dos cantidades es lo único que después va a decir si
-- la reposición 1 a 1 está bien calibrada. Con una sola columna sobreescribible
-- la pantalla se vería idéntica y esa diferencia valdría cero para siempre, sin
-- un solo error que ver -- la falla silenciosa que la regla 4 de CLAUDE.md
-- prohíbe.
--
-- Y sin DEFAULT que copie la propuesta al nacer: con las dos iguales desde el
-- principio, un renglón que nadie revisó y uno que alguien confirmó igual se
-- verían idénticos, y el segundo es justamente la evidencia de que la propuesta
-- acertó.
--
--
-- ## Por qué existe este archivo y no basta con `crear_tablas.sql`
--
-- Se editó `crear_tablas.sql` **también**, y las dos cosas son necesarias. Es
-- la misma razón de la 0001 y **la regla vive en el ADR 0003**, en sus
-- Consecuencias, no en este comentario:
--
-- - `crear_tablas.sql` usa `CREATE TABLE IF NOT EXISTS`, que **calla si la
--   tabla ya existe con otra forma**. Sobre la base de atlas, volver a correrlo
--   no agrega nada y no avisa: las columnas no aparecerían y el primer
--   `UPDATE ... SET cantidad_final = ...` rebotaría con "column cantidad_final
--   of relation renglon does not exist".
-- - Y al revés, dejar las columnas solo aquí haría que una base desde cero
--   naciera sin ellas, y que ese archivo dejara de describir la tabla de verdad
--   -- que es lo único para lo que sirve.
--
--
-- ## Es idempotente, y eso se decidió a propósito
--
-- Correrlo dos veces no rompe nada y no cambia nada la segunda vez. No hay
-- tabla de migraciones aplicadas -- dos migraciones siguen sin justificar un
-- esquema de control-- así que lo que protege contra la segunda corrida es que
-- cada sentencia sea idempotente por sí misma:
--
-- - `ADD COLUMN IF NOT EXISTS` para las tres columnas.
-- - `DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT` para los tres CHECK, porque
--   `ADD CONSTRAINT` **no** tiene `IF NOT EXISTS` en Postgres. Quitar y volver
--   a poner tiene además una propiedad que conviene: el CHECK que queda es el
--   de este archivo, aunque alguien hubiera creado otro con el mismo nombre y
--   otra definición.
--
-- Quitar un CHECK no borra una sola fila. Se hace con credenciales de dueño y
-- en una transacción: si el `ADD` fallara -- porque ya hay filas que lo
-- violan-- el `DROP` se va con él y la tabla se queda como estaba.

SET client_encoding TO 'UTF8';

-- Que no lo corra quien no debe, igual que `crear_tablas.sql`. Con el rol
-- acotado esto fallaría por permisos, pero el mensaje de Postgres no diría
-- cuál es la manera correcta de correrlo.
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

-- Las tres son NULLables y sin DEFAULT. NULL aquí significa "nadie corrigió
-- esta cantidad", que es la inmensa mayoría de los renglones, y un DEFAULT
-- inventaría una decisión que nadie tomó.
ALTER TABLE pedidos.renglon
    ADD COLUMN IF NOT EXISTS cantidad_final integer;

ALTER TABLE pedidos.renglon
    ADD COLUMN IF NOT EXISTS ajustada_por text;

ALTER TABLE pedidos.renglon
    ADD COLUMN IF NOT EXISTS ajustada_en timestamptz;

-- AL MENOS UNA PIEZA: un cero no es una forma de descartar. El porqué completo
-- está en `sql/crear_tablas.sql`, junto a la misma restricción; en corto: un
-- renglón en cero no se pidió, no se descartó, no tiene firma de descarte y
-- sigue contando como trabajo por atender. Para no pedir algo está el estado
-- 'descartado', que guarda quién y cuándo -- y que es lo que el conteo del ADR
-- 0002 mira después de un mes.
ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_cantidad_final;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_cantidad_final
        CHECK (cantidad_final >= 1);

-- La firma vacía no existe, por la misma razón que la clave vacía: una cadena
-- vacía se compara igual que un dato y no se distingue de "no se sabe".
ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_ajustada_por;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_ajustada_por
        CHECK (ajustada_por <> '');

-- Cantidad corregida si y solo si hay firma Y hora, el mismo par que
-- `ck_renglon_descarte`. Sin la mitad de ida, una cantidad cambiada quedaría
-- sin decir quién ni cuándo; sin la de vuelta, una firma colgada diría que
-- alguien corrigió un renglón que nadie tocó.
ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_ajuste;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_ajuste
        CHECK ((cantidad_final IS NOT NULL)
               = (ajustada_por IS NOT NULL AND ajustada_en IS NOT NULL));

COMMENT ON COLUMN pedidos.renglon.cantidad_final IS
    'Lo que una persona decidió pedir, cuando corrigió la propuesta. NULL = '
    'nadie la tocó, nunca la propuesta copiada. Al menos 1: un cero no es una '
    'forma de descartar.';

COMMENT ON COLUMN pedidos.renglon.ajustada_por IS
    'Quién cambió la cantidad, según Cf-Access-Authenticated-User-Email. Es '
    'una FIRMA, no un permiso. NULL si nadie la cambió.';

COMMENT ON COLUMN pedidos.renglon.ajustada_en IS
    'Cuándo se cambió la cantidad, instante con zona. NULL si nadie la cambió.';

COMMIT;


-- --------------------------------------------------------------------------
-- Qué quedó
-- --------------------------------------------------------------------------
--
-- Las tres columnas con su tipo, y los tres CHECK tal como quedaron guardados.
-- Se imprime en vez de darse por hecho, igual que en la 0001: un CHECK puede
-- entrar con el acento deformado y verse bien en el archivo.
--
-- `cantidad_propuesta` sale en la lista A PROPÓSITO: lo que hay que ver de un
-- vistazo es que siguen siendo DOS columnas, no una que se sobreescribe.

SELECT a.attname                                   AS columna,
       format_type(a.atttypid, a.atttypmod)        AS tipo,
       NOT a.attnotnull                            AS admite_nulos
  FROM pg_attribute a
 WHERE a.attrelid = to_regclass('pedidos.renglon')
   AND a.attname IN ('cantidad_propuesta', 'cantidad_final',
                     'ajustada_por', 'ajustada_en')
 ORDER BY a.attname;

SELECT con.conname                        AS restriccion,
       pg_get_constraintdef(con.oid)      AS definicion
  FROM pg_constraint con
 WHERE con.conrelid = to_regclass('pedidos.renglon')
   AND con.conname IN ('ck_renglon_cantidad_final', 'ck_renglon_ajustada_por',
                       'ck_renglon_ajuste')
 ORDER BY con.conname;

\echo ''
\echo '>> Si arriba no salen CUATRO columnas y TRES restricciones, la migracion no quedo.'
\echo '>> cantidad_propuesta y cantidad_final son DOS columnas distintas: la'
\echo '>> primera es inmutable y la diferencia entre las dos es el dato.'
\echo '>> sql/crear_rol.sql NO hace falta volver a correrlo: el GRANT de UPDATE'
\echo '>> es sobre la tabla entera y cubre las columnas nuevas.'
