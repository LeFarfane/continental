-- Veredicto sobre el rol `continental` y sus tres tablas: caso por caso, qué
-- se esperaba y qué se encontró.
--
-- ESTO NO ES UNA LISTA DE BUENOS DESEOS, ES UN GUION QUE DA UN VEREDICTO.
-- Imprime una fila por comprobación con [BIEN], [AVISO] o [MAL], y **termina
-- con error** si algo salió [MAL] -- así el código de salida de psql sirve
-- para un script, y no solo para que alguien lea.
--
-- Correr con credenciales de dueño (usuario `farmacia`), DESPUÉS de
-- `sql/crear_tablas.sql` y `sql/crear_rol.sql`. Desde
-- `~/proyectos/Continental` en atlas:
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 < sql/verificar_rol.sql ; echo "salida: $?"
--
-- Salida 0 = todo bien. Salida 3 = alguna comprobación falló (y la tabla de
-- arriba dice cuál, qué se esperaba y qué pasó).
--
--
-- ## Por qué se pregunta al catálogo y no se intenta la operación
--
-- Se podría entrar como `continental` y probar un `CREATE TABLE` a ver si
-- truena. Se pregunta a `has_table_privilege` y compañía en su lugar por tres
-- razones: no hace falta la contraseña del rol, no escribe nada, y sobre todo
-- **estas funciones toman en cuenta los permisos heredados y los otorgados a
-- PUBLIC**, que es justo por donde se cuela lo que un listado ingenuo de
-- GRANTs no ve. `Marlowe/sql/crear_rol.sql` termina con un `SELECT` sobre
-- `information_schema.role_table_grants`: eso lista los GRANT explícitos al
-- rol y **no vería** un SELECT que le llegue por ser PUBLIC o por pertenecer a
-- otro rol. Aquí se pregunta por el permiso efectivo.
--
-- Si aun así alguien quiere la prueba de fuego desde el otro lado, al final
-- del archivo están los dos comandos que la hacen, con el error exacto que
-- deben devolver.

SET client_encoding TO 'UTF8';
\pset format aligned
\pset border 2

-- Sin rol no hay nada que verificar, y `has_table_privilege` sobre un rol
-- inexistente tumbaría el guion a media tabla con un error que no explica
-- nada. Se falla aquí, temprano y diciendo qué falta.
DO $guardia$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'continental') THEN
        RAISE EXCEPTION '%',
            'VEREDICTO: MAL. El rol continental no existe. Corre primero '
            || 'sql/crear_tablas.sql y luego sql/crear_rol.sql.';
    END IF;
END
$guardia$;

CREATE TEMP TABLE resultado_verificacion (
    n         integer NOT NULL,
    caso      text    NOT NULL,
    esperado  text,
    obtenido  text,
    ok        boolean,
    severidad text    NOT NULL DEFAULT 'MAL'
);

INSERT INTO resultado_verificacion (n, caso, esperado, obtenido, ok) VALUES

-- ---------------------------------------------------------------- el rol
(1,
 'El rol no tiene atributos de administrador',
 'ninguno',
 (SELECT coalesce(nullif(concat_ws(', ',
             CASE WHEN rolsuper       THEN 'SUPERUSER'   END,
             CASE WHEN rolcreatedb    THEN 'CREATEDB'    END,
             CASE WHEN rolcreaterole  THEN 'CREATEROLE'  END,
             CASE WHEN rolbypassrls   THEN 'BYPASSRLS'   END,
             CASE WHEN rolreplication THEN 'REPLICATION' END), ''), 'ninguno')
    FROM pg_roles WHERE rolname = 'continental'),
 NULL),

-- Un rol acotado que pertenece a otro rol no está acotado: hereda todo lo
-- suyo. `pg_read_all_data` es el caso extremo -- basta esa pertenencia para
-- que lea el almacén entero sin un solo GRANT sobre una tabla.
(2,
 'El rol no hereda permisos de ningún otro rol',
 'ninguno',
 (SELECT coalesce(string_agg(r.rolname, ', ' ORDER BY r.rolname), 'ninguno')
    FROM pg_roles r
   WHERE r.rolname <> 'continental'
     AND pg_has_role('continental', r.oid, 'USAGE')),
 NULL),

-- ------------------------------------------------------ dónde viven y de quién
(3,
 'El esquema `pedidos` existe y NO lo posee continental',
 'existe, con otro propietario',
 (SELECT coalesce(
            (SELECT CASE WHEN pg_get_userbyid(nspowner) = 'continental'
                         THEN 'LO POSEE continental'
                         ELSE 'existe, propietario: ' || pg_get_userbyid(nspowner)
                    END
               FROM pg_namespace WHERE nspname = 'pedidos'),
            'NO EXISTE')),
 (SELECT EXISTS (SELECT 1 FROM pg_namespace
                  WHERE nspname = 'pedidos'
                    AND pg_get_userbyid(nspowner) <> 'continental'))),

(4,
 'Las tres tablas existen y NO las posee continental',
 '3 tablas, con otro propietario',
 (SELECT format('%s tabla(s): %s', count(*),
                coalesce(string_agg(c.relname || ' -> ' || pg_get_userbyid(c.relowner),
                                    ', ' ORDER BY c.relname), '--'))
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'pedidos' AND c.relkind = 'r'),
 (SELECT count(*) = 3
         AND count(*) FILTER (WHERE pg_get_userbyid(c.relowner) = 'continental') = 0
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'pedidos' AND c.relkind = 'r')),

-- ------------------------------------------------- lo que SÍ tiene que poder
(5,
 'continental puede USAR el esquema `pedidos`',
 'sí',
 -- El `WHEN` del esquema inexistente va primero a propósito: sin él,
 -- `has_schema_privilege` sobre un esquema que no existe no devuelve `false`,
 -- **truena**, y se lleva por delante el INSERT entero -- el guion moriría a
 -- media tabla en vez de decir qué falta.
 (SELECT CASE
           WHEN NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'pedidos')
                THEN 'el esquema `pedidos` no existe'
           WHEN has_schema_privilege('continental', 'pedidos', 'USAGE')
                THEN 'sí'
           ELSE 'NO'
         END),
 NULL),

(6,
 'continental puede SELECT, INSERT y UPDATE sus tres tablas',
 'no le falta ninguno',
 (SELECT coalesce(string_agg(x.tabla || ': le falta ' || x.priv, '; '
                             ORDER BY x.tabla, x.priv),
                  'no le falta ninguno')
    FROM (SELECT c.oid, n.nspname || '.' || c.relname AS tabla, p AS priv
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace,
                 unnest(ARRAY['SELECT', 'INSERT', 'UPDATE']) AS p
           WHERE n.nspname = 'pedidos' AND c.relkind = 'r') x
   WHERE NOT has_table_privilege('continental', x.oid, x.priv)),
 NULL),

(7,
 'continental lee exactamente las cinco tablas de `marts` que necesita',
 'dim_fecha, dim_producto, dim_proveedor, fct_compras, fct_ventas',
 (SELECT coalesce(string_agg(c.relname, ', ' ORDER BY c.relname), 'ninguna')
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'marts'
     AND c.relkind IN ('r', 'v', 'm', 'f', 'p')
     AND has_table_privilege('continental', c.oid, 'SELECT')),
 NULL),

-- ------------------------------------------------ lo que NO tiene que poder
(8,
 'continental NO puede crear objetos en NINGÚN esquema',
 'ningún esquema',
 (SELECT coalesce(string_agg(n.nspname, ', ' ORDER BY n.nspname), 'ningún esquema')
    FROM pg_namespace n
   WHERE n.nspname NOT LIKE 'pg\_%'
     AND n.nspname <> 'information_schema'
     AND has_schema_privilege('continental', n.oid, 'CREATE')),
 NULL),

(9,
 'continental NO puede borrar ni vaciar sus propias tablas',
 'ninguno',
 (SELECT coalesce(string_agg(x.tabla || ': tiene ' || x.priv, '; '
                             ORDER BY x.tabla, x.priv),
                  'ninguno')
    FROM (SELECT c.oid, n.nspname || '.' || c.relname AS tabla, p AS priv
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace,
                 unnest(ARRAY['DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER']) AS p
           WHERE n.nspname = 'pedidos' AND c.relkind = 'r') x
   WHERE has_table_privilege('continental', x.oid, x.priv)),
 NULL),

-- Dinámico a propósito: no hay lista de esquemas prohibidos que mantener, así
-- que un `raw`, `curado` o `staging` nuevo entra solo a la comprobación.
(10,
 'continental NO lee nada fuera de `marts` y `pedidos`',
 'nada',
 (SELECT coalesce(string_agg(n.nspname || '.' || c.relname, ', '
                             ORDER BY n.nspname, c.relname), 'nada')
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE c.relkind IN ('r', 'v', 'm', 'f', 'p')
     AND n.nspname NOT LIKE 'pg\_%'
     AND n.nspname <> 'information_schema'
     AND n.nspname NOT IN ('marts', 'pedidos')
     AND has_table_privilege('continental', c.oid, 'SELECT')),
 NULL),

(11,
 'continental NO escribe nada fuera de `pedidos`',
 'nada',
 (SELECT coalesce(string_agg(DISTINCT n.nspname || '.' || c.relname, ', '), 'nada')
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace,
         unnest(ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE']) AS p
   WHERE c.relkind IN ('r', 'v', 'm', 'f', 'p')
     AND n.nspname NOT LIKE 'pg\_%'
     AND n.nspname <> 'information_schema'
     AND n.nspname <> 'pedidos'
     AND has_table_privilege('continental', c.oid, p)),
 NULL),

-- ---------------------------------------------- la forma de las tres tablas
--
-- `CREATE TABLE IF NOT EXISTS` calla si la tabla ya existe con otra forma, así
-- que comprobar solo los permisos dejaría pasar un DDL editado a medias.

(12,
 '"Uno por día y negocio" lo impide la BASE, no el código',
 'hay una restricción UNIQUE (negocio, fecha_del_pedido)',
 (SELECT coalesce(string_agg(pg_get_constraintdef(con.oid), '; '), 'NO HAY NINGUNA')
    FROM pg_constraint con
   WHERE con.conrelid = to_regclass('pedidos.pedido_sugerido')
     AND con.contype = 'u'),
 (SELECT EXISTS (SELECT 1 FROM pg_constraint con
                  WHERE con.conrelid = to_regclass('pedidos.pedido_sugerido')
                    AND con.contype = 'u'
                    AND pg_get_constraintdef(con.oid)
                        ILIKE '%UNIQUE (negocio, fecha_del_pedido)%'))),

-- `money` entra en la lista junto a los flotantes: depende de `lc_monetary`
-- del servidor, así que el mismo valor se lee distinto según cómo arranque el
-- contenedor. Dinero es `numeric` y punto.
(13,
 'Ninguna columna de `pedidos` guarda números en coma flotante',
 'ninguna',
 (SELECT coalesce(string_agg(table_name || '.' || column_name || ' (' || data_type || ')',
                             ', ' ORDER BY table_name, column_name), 'ninguna')
    FROM information_schema.columns
   WHERE table_schema = 'pedidos'
     AND data_type IN ('real', 'double precision', 'money')),
 NULL),

(14,
 'Las tres tablas dicen a qué negocio pertenecen (regla 7)',
 'ninguna sin negocio',
 (SELECT coalesce(string_agg(c.relname, ', ' ORDER BY c.relname), 'ninguna sin negocio')
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'pedidos' AND c.relkind = 'r'
     AND NOT EXISTS (SELECT 1 FROM information_schema.columns col
                      WHERE col.table_schema = 'pedidos'
                        AND col.table_name = c.relname
                        AND col.column_name = 'negocio'
                        AND col.is_nullable = 'NO')),
 NULL),

-- Si psql mandó el DDL como latin1, el acento entró deformado DENTRO del
-- CHECK y el primer `UPDATE ... SET estado = 'en tránsito'` de Continental
-- rebotaría con una violación de restricción que nadie sabría explicar.
(15,
 'El acento de "en tránsito" sobrevivió al CHECK del renglón',
 'el CHECK contiene ''en tránsito''',
 -- El `coalesce` va FUERA del subconsulta: si la restricción no existe, la
 -- subconsulta devuelve cero filas y no una fila con NULL, así que un
 -- `coalesce` por dentro no atraparía nada y la casilla saldría vacía.
 coalesce(
   (SELECT pg_get_constraintdef(con.oid)
      FROM pg_constraint con
     WHERE con.conrelid = to_regclass('pedidos.renglon')
       AND con.conname = 'ck_renglon_estado'),
   'NO EXISTE ck_renglon_estado'),
 (SELECT EXISTS (SELECT 1 FROM pg_constraint con
                  WHERE con.conrelid = to_regclass('pedidos.renglon')
                    AND con.conname = 'ck_renglon_estado'
                    AND pg_get_constraintdef(con.oid) LIKE '%en tránsito%'))),

-- Las llaves son de identidad y no `serial`. La diferencia es un permiso:
-- `serial` exige además USAGE sobre la secuencia, que se olvida y se
-- manifiesta como "permission denied for sequence" en el primer INSERT.
(16,
 'Las tres llaves son GENERATED AS IDENTITY (no hacen falta permisos de secuencia)',
 '3',
 (SELECT count(*)::text
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'pedidos' AND c.relkind = 'r' AND a.attidentity <> ''),
 NULL),

-- AVISO y no MAL: una tabla temporal vive en la sesión, no puede leer nada que
-- el rol no pueda leer ya, y desaparece al desconectarse. El permiso llega por
-- el TEMPORARY que PUBLIC tiene sobre la base por omisión, y quitarlo sería
-- `REVOKE TEMPORARY ... FROM PUBLIC`, que afecta a dbt y a Metabase por igual.
-- Se deja documentado en vez de arreglado a ciegas: cambiarlo es una decisión
-- de farmacia-data, no de Continental.
(17,
 'continental puede crear tablas TEMPORALES (excepción conocida)',
 'no',
 (SELECT CASE WHEN has_database_privilege('continental', current_database(), 'TEMP')
              THEN 'sí' ELSE 'no' END),
 NULL);

UPDATE resultado_verificacion SET severidad = 'AVISO' WHERE n = 17;
UPDATE resultado_verificacion
   SET ok = coalesce(obtenido = esperado, false)
 WHERE ok IS NULL;


-- --------------------------------------------------------------------------
-- El veredicto
-- --------------------------------------------------------------------------

\echo ''
\echo '=========== VERIFICACION DEL ROL continental ==========='
\echo ''

SELECT n,
       CASE WHEN ok THEN '[BIEN]' ELSE '[' || severidad || ']' END AS veredicto,
       caso,
       esperado,
       obtenido
  FROM resultado_verificacion
 ORDER BY CASE WHEN ok THEN 2
               WHEN severidad = 'MAL' THEN 0
               ELSE 1
          END,
          n;

DO $veredicto$
DECLARE
    malos  integer;
    avisos integer;
    total  integer;
BEGIN
    SELECT count(*) FILTER (WHERE NOT ok AND severidad = 'MAL'),
           count(*) FILTER (WHERE NOT ok AND severidad = 'AVISO')
      INTO malos, avisos
      FROM resultado_verificacion;

    IF malos > 0 THEN
        RAISE EXCEPTION '%', format(
            'VEREDICTO: MAL. %s comprobacion(es) fallaron (y %s aviso(s)). '
            || 'Mira las filas [MAL] de arriba: cada una dice qué se esperaba '
            || 'y qué se encontró. Si falta alguna tabla de marts, lo más '
            || 'probable es que un dbt build se llevó el GRANT por delante: '
            || 'lee el final de sql/crear_rol.sql.',
            malos, avisos)
        USING ERRCODE = 'insufficient_privilege';
    END IF;

    SELECT count(*) INTO total FROM resultado_verificacion;
    RAISE NOTICE '%', format(
        'VEREDICTO: BIEN. Pasaron %s de %s comprobaciones, con %s aviso(s) '
        || 'conocido(s). El rol escribe sus tres tablas, lee las cinco de '
        || 'marts y no puede crear tablas ni leer el resto del almacén.',
        total - avisos, total, avisos);
END
$veredicto$;


-- --------------------------------------------------------------------------
-- Apéndice: la prueba de fuego desde el otro lado (opcional)
-- --------------------------------------------------------------------------
--
-- Lo de arriba pregunta al catálogo. Si además se quiere ver al rol rebotar de
-- verdad, esto se corre CON LA CONTRASEÑA DE `continental` y tiene que fallar
-- las dos veces:
--
--   docker exec -i -e PGPASSWORD='LA_DE_CONTINENTAL' farmacia_warehouse \
--       psql -U continental -d farmacia -c 'CREATE TABLE pedidos.colada (x int);'
--   -- esperado: ERROR:  permission denied for schema pedidos
--
--   docker exec -i -e PGPASSWORD='LA_DE_CONTINENTAL' farmacia_warehouse \
--       psql -U continental -d farmacia -c 'SELECT count(*) FROM marts.fct_merma;'
--   -- esperado: ERROR:  permission denied for table fct_merma
--
-- Si alguno de los dos DEVUELVE UN RESULTADO en vez de un error, el rol no
-- quedó acotado -- y entonces la tabla de arriba está midiendo otra cosa.
