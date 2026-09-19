-- 0001 - `pedidos.renglon` gana `descartado_por` y `descartado_en` (ticket 10).
--
-- SE CORRE A MANO, UNA VEZ, CON CREDENCIALES DE DUEÑO, igual que
-- `sql/crear_tablas.sql` y por la misma razón (ADR 0003): esto es DDL, y el rol
-- `continental` no puede hacer DDL a propósito. **No lo corre el servicio, no
-- lo corre una prueba y no lo corre el lote de la noche.** Si algún día el
-- código de arranque aplica migraciones solo, el rol necesitaría ALTER sobre
-- sus tablas -- y con ALTER puede quitar un CHECK, que es la mitad de las
-- garantías de este esquema.
--
-- Desde `~/proyectos/Farmacia/Continental` en atlas:
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 < sql/migraciones/0001-renglon-quien-descarto-y-cuando.sql
--
-- `<` y no `-f`: con `docker exec`, el `-f` de psql busca el archivo DENTRO
-- del contenedor, donde este repo no está montado. `ON_ERROR_STOP=1` porque
-- sin él psql sigue tras un error y termina diciendo que todo salió bien.
--
--
-- ## Por qué existe este archivo y no basta con editar `crear_tablas.sql`
--
-- Se editó `crear_tablas.sql` **también**, y las dos cosas son necesarias:
--
-- - `crear_tablas.sql` usa `CREATE TABLE IF NOT EXISTS`, que **calla si la
--   tabla ya existe con otra forma**. Sobre la base de atlas, donde
--   `pedidos.renglon` ya puede estar creada, volver a correrlo no agrega nada
--   y no avisa de nada: la columna no aparecería y el primer
--   `UPDATE ... SET descartado_por = ...` rebotaría con "column
--   descartado_por of relation renglon does not exist".
-- - Y al revés, dejar la columna solo aquí haría que una base creada desde
--   cero con `crear_tablas.sql` naciera sin ella, y que ese archivo dejara de
--   describir la tabla de verdad -- que es lo único para lo que sirve.
--
-- Así que una columna nueva se escribe en los dos archivos:
-- `crear_tablas.sql` es la forma a la que se quiere llegar y
-- `sql/migraciones/NNNN-*.sql` es cómo llega una base que ya existe. **La
-- regla vive en el ADR 0003**, en sus Consecuencias, y no en este comentario:
-- una convención del repo escrita solo aquí no la encuentra quien agregue la
-- siguiente columna.
--
--
-- ## Es idempotente, y eso se decidió a propósito
--
-- Correrlo dos veces no rompe nada y no cambia nada la segunda vez. No hay
-- tabla de migraciones aplicadas -- una sola migración no justifica inventar
-- un esquema de control-- así que lo que protege contra la segunda corrida es
-- que cada sentencia sea idempotente por sí misma:
--
-- - `ADD COLUMN IF NOT EXISTS` para las dos columnas.
-- - `DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT` para los dos CHECK, porque
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

-- Las dos son NULLables y sin DEFAULT, y eso no contradice la regla 7 (toda
-- tabla dice a qué negocio pertenece): aquí NULL significa "este renglón no
-- está descartado", que es la inmensa mayoría. Un DEFAULT inventaría una firma
-- para renglones que nadie tocó.
ALTER TABLE pedidos.renglon
    ADD COLUMN IF NOT EXISTS descartado_por text;

ALTER TABLE pedidos.renglon
    ADD COLUMN IF NOT EXISTS descartado_en timestamptz;

-- La firma vacía no existe, por la misma razón que la clave vacía: una cadena
-- vacía se compara igual que un dato y no se distingue de "no se sabe".
ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_descartado_por;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_descartado_por
        CHECK (descartado_por <> '');

-- Descartado si y solo si hay firma Y hora. El porqué de las dos mitades está
-- en `sql/crear_tablas.sql`, junto a la misma restricción: sin `descartado_en`
-- la condición de revisión del ADR 0002 -"los descartados de un mes"- no se
-- puede evaluar, y sin la mitad de vuelta un renglón devuelto a 'abierto'
-- seguiría contando como descartado en ese mismo conteo.
ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_descarte;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_descarte
        CHECK ((estado = 'descartado')
               = (descartado_por IS NOT NULL AND descartado_en IS NOT NULL));

COMMENT ON COLUMN pedidos.renglon.descartado_por IS
    'Quién descartó el renglón, según Cf-Access-Authenticated-User-Email. Es '
    'una FIRMA, no un permiso. NULL en todo renglón que no esté descartado.';

COMMENT ON COLUMN pedidos.renglon.descartado_en IS
    'Cuándo se descartó, instante con zona. NULL en todo renglón que no esté '
    'descartado. Es lo que hace medible la condición de revisión del ADR 0002.';

COMMIT;


-- --------------------------------------------------------------------------
-- Qué quedó
-- --------------------------------------------------------------------------
--
-- Las dos columnas con su tipo, y los dos CHECK tal como quedaron guardados.
-- Se imprime en vez de darse por hecho: la comprobación 15 de
-- `verificar_rol.sql` existe porque un CHECK puede entrar con el acento
-- deformado y verse bien en el archivo.

SELECT a.attname                                   AS columna,
       format_type(a.atttypid, a.atttypmod)        AS tipo,
       NOT a.attnotnull                            AS admite_nulos
  FROM pg_attribute a
 WHERE a.attrelid = to_regclass('pedidos.renglon')
   AND a.attname IN ('descartado_por', 'descartado_en')
 ORDER BY a.attname;

SELECT con.conname                        AS restriccion,
       pg_get_constraintdef(con.oid)      AS definicion
  FROM pg_constraint con
 WHERE con.conrelid = to_regclass('pedidos.renglon')
   AND con.conname IN ('ck_renglon_descartado_por', 'ck_renglon_descarte')
 ORDER BY con.conname;

\echo ''
\echo '>> Si arriba no salen DOS columnas y DOS restricciones, la migracion no quedo.'
\echo '>> sql/crear_rol.sql NO hace falta volver a correrlo: el GRANT de UPDATE'
\echo '>> es sobre la tabla entera y cubre las columnas nuevas.'
