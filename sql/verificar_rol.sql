-- Veredicto sobre el rol `continental` y sus cinco tablas: caso por caso, qué
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

-- CINCO desde el ticket 19, que estrenó `pedidos.corrida_del_lote` (ADR
-- 0007); eran cuatro desde el ticket 12 y tres al principio. El número está
-- escrito a mano A PROPÓSITO: si alguien crea una sexta tabla en este esquema
-- sin pasar por `crear_tablas.sql`, esta comprobación se pone en [MAL] en vez
-- de darla por buena. El DDL se corre a mano una vez, así que agregar una
-- tabla es un acto deliberado y debe verse como tal.
(4,
 'Las cinco tablas existen y NO las posee continental',
 '5 tablas, con otro propietario',
 (SELECT format('%s tabla(s): %s', count(*),
                coalesce(string_agg(c.relname || ' -> ' || pg_get_userbyid(c.relowner),
                                    ', ' ORDER BY c.relname), '--'))
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'pedidos' AND c.relkind = 'r'),
 (SELECT count(*) = 5
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

-- Dinámico a propósito: recorre TODAS las tablas de `pedidos`, así que la
-- quinta -- y la sexta, el día que la haya-- entra sola. Es la comprobación
-- que caza el olvido más caro de este esquema: una migración que crea una
-- tabla y a la que nadie le corrió `crear_rol.sql` después. El GRANT no se
-- puede dar sobre una tabla que no existía, y el síntoma aparece en atlas como
-- "permission denied for table ..." en el primer INSERT -- o, con la quinta, a
-- las 22:00 y sin nadie mirando.
(6,
 'continental puede SELECT, INSERT y UPDATE sus cinco tablas',
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

-- --------------------------------------------- la forma de las cinco tablas
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
 'Todas las tablas dicen a qué negocio pertenecen (regla 7)',
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
--
-- SE COMPARA CONTRA EL NÚMERO DE TABLAS DEL ESQUEMA Y NO CONTRA UN NÚMERO
-- ESCRITO A MANO, y eso es un arreglo del ticket 19: hasta aquí esperaba `3`
-- cuando ya eran cuatro desde el ticket 12, así que **habría salido [MAL]
-- sobre una base correcta la primera vez que alguien lo corriera** -- y nadie
-- lo había corrido nunca (`HANDOVER.md`). Un verificador que da un falso [MAL]
-- es tan malo como uno que da un falso [BIEN]: los dos enseñan a no creerle.
--
-- Lo que de verdad se quiere afirmar es "**una** llave de identidad por tabla,
-- ninguna `serial`", y eso se escribe con `count(*)` contra `count(*)`: la
-- sexta tabla entra sola y esta comprobación no hay que volver a tocarla. El
-- número esperado no es una constante de este archivo, así que se calcula en
-- `obtenido` y se compara en `ok` -- por eso aquí `ok` no es NULL.
(16,
 'Cada tabla tiene UNA llave GENERATED AS IDENTITY (no hacen falta permisos de secuencia)',
 'una por tabla',
 (SELECT format('%s columna(s) de identidad en %s tabla(s)',
                count(*) FILTER (WHERE a.attidentity <> ''),
                count(DISTINCT c.oid))
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN pg_attribute a
           ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
   WHERE n.nspname = 'pedidos' AND c.relkind = 'r'),
 (SELECT count(*) FILTER (WHERE a.attidentity <> '') = count(DISTINCT c.oid)
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN pg_attribute a
           ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
   WHERE n.nspname = 'pedidos' AND c.relkind = 'r')),

-- ------------------------------------------- la forma del precio congelado
--
-- El ticket 12 guarda dinero, y el dinero es donde este esquema tiene más que
-- perder. Tres comprobaciones, y cada una caza una falla que no se ve.

-- Si la tabla quedó con un UNIQUE sobre (renglón, proveedor), alguien
-- convirtió el diseño en "una fila por proveedor" y el código -- que solo hace
-- INSERT-- empezaría a rebotar en la segunda consulta de un renglón. Peor si
-- además alguien "arregla" eso con un UPSERT: entonces una consulta fallida
-- borraría un precio bueno, en silencio. Esta tabla SOLO CRECE.
(18,
 'El precio congelado se AGREGA: no hay UNIQUE que obligue a pisarlo',
 'ninguna restricción única de más',
 (SELECT coalesce(string_agg(pg_get_constraintdef(con.oid), '; '),
                  'ninguna restricción única de más')
    FROM pg_constraint con
   WHERE con.conrelid = to_regclass('pedidos.precio_de_proveedor')
     AND con.contype = 'u'),
 NULL),

-- Los ocho motivos de `precios.MOTIVOS`, leídos DE VUELTA desde el catálogo.
-- Se compara contra el texto entero y con sus acentos: si psql mandó el DDL
-- como latin1, el CHECK guardó 'el portal no contestÃ³' y el primer INSERT con
-- motivo rebotaría con una violación de restricción que nadie sabría explicar.
-- Es la misma trampa que la comprobación 15 caza para 'en tránsito', y aquí
-- son ocho textos en vez de uno.
(19,
 'Los ocho motivos del precio sobrevivieron al CHECK, con sus acentos',
 'están los ocho',
 coalesce(
   (SELECT CASE
             WHEN pg_get_constraintdef(con.oid) LIKE '%sin resultados%'
              AND pg_get_constraintdef(con.oid) LIKE '%varios resultados%'
              AND pg_get_constraintdef(con.oid) LIKE '%no empareja%'
              AND pg_get_constraintdef(con.oid) LIKE '%el portal no contestó%'
              AND pg_get_constraintdef(con.oid) LIKE '%la sesión caducó%'
              AND pg_get_constraintdef(con.oid) LIKE '%no se sabe leer la página%'
              AND pg_get_constraintdef(con.oid) LIKE '%no alcanzó el tiempo%'
              AND pg_get_constraintdef(con.oid) LIKE '%precio ilegible%'
                  THEN 'están los ocho'
             ELSE pg_get_constraintdef(con.oid)
           END
      FROM pg_constraint con
     WHERE con.conrelid = to_regclass('pedidos.precio_de_proveedor')
       AND con.conname = 'ck_precio_motivo_conocido'),
   'NO EXISTE ck_precio_motivo_conocido'),
 NULL),

-- LAS DOS RESTRICCIONES QUE IMPIDEN QUE UN HUECO SE VEA COMO EL MÁS BARATO.
-- `ck_precio_positivo` prohíbe el cero -- el único número que aquí hace daño--
-- y `ck_precio_sin_dato` obliga a que todo precio faltante traiga su motivo.
-- Sin la primera, un 0.00 gana toda comparación; sin la segunda, un NULL mudo
-- deja al encargado sin saber si lo puede resolver él (historia 23).
(20,
 'Un precio nunca puede ser cero, y un hueco nunca puede ser mudo',
 'están las dos',
 (SELECT CASE count(*) WHEN 2 THEN 'están las dos'
                       ELSE format('solo %s: %s', count(*),
                                   coalesce(string_agg(con.conname, ', '), '--'))
         END
    FROM pg_constraint con
   WHERE con.conrelid = to_regclass('pedidos.precio_de_proveedor')
     AND con.conname IN ('ck_precio_positivo', 'ck_precio_sin_dato')),
 NULL),

-- ------------------------------------------ la forma de la corrida del lote
--
-- El ticket 19 estrena la quinta tabla, y lo que esta tabla tiene que perder
-- no es dinero: es la capacidad de la pantalla de decir por qué un renglón no
-- tiene precio. Dos comprobaciones, y cada una caza una falla que no se ve.

-- LOS CUATRO FINALES, LEÍDOS DE VUELTA DESDE EL CATÁLOGO, CON SUS ACENTOS. Es
-- la misma trampa que las comprobaciones 15 y 19 cazan para 'en tránsito' y
-- para los ocho motivos del precio, y aquí muerde más fuerte: quien escribe en
-- esta tabla es el LOTE, a las 22:00 y sin nadie mirando. Si psql mandó el DDL
-- como latin1, el CHECK guardó 'terminÃ³' y el primer INSERT rebota con una
-- violación de restricción que nadie va a ver hasta la mañana -- y la pantalla
-- entonces dirá "el lote no corrió sobre esta lista", que es exactamente lo
-- contrario de lo que pasó.
(21,
 'Los cuatro finales de la corrida sobrevivieron al CHECK, con sus acentos',
 'están los cuatro',
 coalesce(
   (SELECT CASE
             WHEN pg_get_constraintdef(con.oid) LIKE '%terminó%'
              AND pg_get_constraintdef(con.oid) LIKE '%se acabó el tiempo%'
              AND pg_get_constraintdef(con.oid) LIKE '%se interrumpió%'
              AND pg_get_constraintdef(con.oid) LIKE '%no hubo lista%'
                  THEN 'están los cuatro'
             ELSE pg_get_constraintdef(con.oid)
           END
      FROM pg_constraint con
     WHERE con.conrelid = to_regclass('pedidos.corrida_del_lote')
       AND con.conname = 'ck_corrida_final'),
   'NO EXISTE ck_corrida_final'),
 NULL),

-- LAS TRES RESTRICCIONES QUE IMPIDEN QUE LA PANTALLA ESCRIBA UN ABSURDO.
-- `ck_corrida_consultados` y `ck_corrida_con_precio` son el par de números con
-- el que se escribe "el lote consultó 210 de 380": un numerador mayor que el
-- denominador se lee como una pantalla rota, no como un dato. `ck_corrida_lista`
-- obliga a que la lista y su fecha vayan juntas o no vayan -- con una sola de
-- las dos, la pantalla busca por id y escribe la fecha de otra noche.
(22,
 'La corrida no puede guardar un conteo imposible ni media lista',
 'están las tres',
 (SELECT CASE count(*) WHEN 3 THEN 'están las tres'
                       ELSE format('solo %s: %s', count(*),
                                   coalesce(string_agg(con.conname, ', '), '--'))
         END
    FROM pg_constraint con
   WHERE con.conrelid = to_regclass('pedidos.corrida_del_lote')
     AND con.conname IN ('ck_corrida_consultados', 'ck_corrida_con_precio',
                         'ck_corrida_lista')),
 NULL),

-- ------------------------------------- el puente con SICAR y la elección (20)
--
-- El ticket 20 no estrena tabla: aprieta dos restricciones que ya existían y
-- afloja una columna a propósito. Las tres cosas se pueden ver bien en el
-- archivo y estar mal en la base, y las tres tienen una consecuencia concreta.

-- LA IDENTIDAD DEL PEDIDO ES LA CLAVE DE DOYLE (ADR 0008), Y EL pro_id DE
-- SICAR PUEDE FALTAR. Si `proveedor` no quedó NOT NULL, se podría guardar un
-- pedido sin saber a quién se le pide; si `proveedor_id` se quedó NOT NULL, a
-- QuePharma NO SE LE VA A PODER PEDIR -- no tiene fila en `marts.dim_proveedor`
-- (22 filas, medido el 2026-09-19) y nunca la ha tenido, porque la farmacia no
-- le ha comprado. Las dos mitades se miran juntas porque juntas son la
-- decisión.
(23,
 'El pedido se identifica por la clave de Doyle y el proveedor_id de SICAR puede faltar',
 'proveedor NOT NULL, proveedor_id admite nulos',
 (SELECT coalesce(
           string_agg(a.attname
                      || CASE WHEN a.attnotnull THEN ' NOT NULL'
                              ELSE ' admite nulos' END,
                      -- ASCENDENTE, y no es cosmético: el veredicto es una
                      -- comparación de cadenas (`ok = (obtenido = esperado)`),
                      -- así que el orden forma parte del valor. Con `DESC`
                      -- esto armaba `proveedor_id ..., proveedor ...` contra
                      -- un esperado escrito al revés, y el caso salía [MAL]
                      -- con la base perfectamente bien. Lo cazó la primera
                      -- corrida de verdad, el 2026-09-19.
                      ', ' ORDER BY a.attname),
           'NO EXISTEN esas columnas')
    FROM pg_attribute a
   WHERE a.attrelid = to_regclass('pedidos.pedido')
     AND a.attname IN ('proveedor', 'proveedor_id')
     AND NOT a.attisdropped),
 NULL),

-- "UNO POR PROVEEDOR DENTRO DE LA MISMA LISTA", Y TIENE QUE ESTAR SOBRE LA
-- CLAVE DE DOYLE. Es la comprobación que caza el error más silencioso de esta
-- migración: dejar el UNIQUE sobre `proveedor_id` después de permitirle nulos
-- **no impide nada**, porque en Postgres dos nulos no se consideran iguales
-- dentro de un UNIQUE. Dos pedidos a QuePharma entrarían los dos -- dos veces
-- la misma mercancía-- sin un solo error que ver.
--
-- Y es además la restricción que `almacenamiento._ABRIR_EL_PEDIDO` nombra en su
-- `ON CONFLICT ON CONSTRAINT`: con otra definición, partir dos veces dejaría
-- de reencontrar el pedido que ya estaba.
(24,
 'Uno por proveedor está sobre la CLAVE DE DOYLE y no sobre proveedor_id',
 'UNIQUE (pedido_sugerido_id, proveedor)',
 coalesce(
   (SELECT pg_get_constraintdef(con.oid)
      FROM pg_constraint con
     WHERE con.conrelid = to_regclass('pedidos.pedido')
       AND con.conname = 'ux_pedido_proveedor'),
   'NO EXISTE ux_pedido_proveedor'),
 NULL),

-- UN RENGLÓN PERTENECE A UN SOLO PEDIDO, **Y A UNO DE SU PROPIA LISTA**. Lo
-- primero lo sostiene que `pedido_id` sea una columna y no una tabla de cruce;
-- lo segundo es lo que el ticket 20 agregó a la llave. Con solo
-- `(pedido_id, negocio)`, un renglón de la lista del martes podía colgar de un
-- pedido de la del lunes: la restricción se cumplía y el total de ese pedido
-- contaba mercancía de otro día.
(25,
 'Un renglón solo puede colgar de un pedido de SU misma lista',
 'FOREIGN KEY (pedido_id, pedido_sugerido_id, negocio) REFERENCES pedidos.pedido(pedido_id, pedido_sugerido_id, negocio)',
 coalesce(
   (SELECT pg_get_constraintdef(con.oid)
      FROM pg_constraint con
     WHERE con.conrelid = to_regclass('pedidos.renglon')
       AND con.conname = 'fk_renglon_pedido'),
   'NO EXISTE fk_renglon_pedido'),
 NULL),

-- LAS DOS RESTRICCIONES QUE HACEN AUDITABLE LA ELECCIÓN. `ck_renglon_eleccion`
-- es el par firma-y-hora, el mismo de `ck_renglon_descarte` y
-- `ck_renglon_ajuste`: sin él, un renglón podría decir que se le compra a LEVIC
-- sin decir quién lo decidió -- y ésa es la pregunta entera del ticket 20.
-- `ck_pedido_estado` es lo que hace que "nacen en borrador" sea una garantía de
-- la base y no una costumbre del código.
(26,
 'La elección va firmada y el pedido nace en borrador',
 'están las dos',
 (SELECT CASE count(*) WHEN 2 THEN 'están las dos'
                       ELSE format('solo %s: %s', count(*),
                                   coalesce(string_agg(con.conname, ', '), '--'))
         END
    FROM pg_constraint con
   WHERE (con.conrelid = to_regclass('pedidos.renglon')
          AND con.conname = 'ck_renglon_eleccion')
      OR (con.conrelid = to_regclass('pedidos.pedido')
          AND con.conname = 'ck_pedido_estado')),
 NULL),

-- LOS DOS ESTADOS DEL PEDIDO, Y QUE LA FIRMA DEL ENVÍO ESTÉ PAREADA (ticket 21,
-- ADR 0009). Se leen del catálogo y no del archivo: los dos se pueden ver
-- impecables en `crear_tablas.sql` y estar mal en la base -- si la migración 0006
-- no se corrió, el CHECK sigue diciendo solo `borrador` y el primer clic en
-- "Enviar" rebota en atlas contra una violación de restricción que el encargado
-- va a ver como "algo falló" (regla 5 de CLAUDE.md).
--
-- Se compara el texto normalizado de `pg_get_constraintdef` porque lo que
-- importa es qué VALORES acepta, no cómo los escribió quien lo creó.
(27,
 'El pedido puede estar en borrador Y en enviado',
 'los dos',
 (SELECT CASE
           WHEN def IS NULL THEN 'NO EXISTE ck_pedido_estado'
           WHEN def LIKE '%''borrador''%' AND def LIKE '%''enviado''%'
                THEN 'los dos'
           ELSE 'solo: ' || def
         END
    FROM (SELECT pg_get_constraintdef(con.oid) AS def
            FROM pg_constraint con
           WHERE con.conrelid = to_regclass('pedidos.pedido')
             AND con.conname = 'ck_pedido_estado') AS c),
 NULL),

-- LA FIRMA DEL ENVÍO, PAREADA EN LOS DOS SENTIDOS. `enviado` quiere decir "yo
-- ya lo capturé en el portal del proveedor" (ADR 0009): es la declaración de una
-- persona sobre algo que Continental NO VIO, así que sin su firma no queda
-- ningún hecho guardado -- solo un "se envió" en voz pasiva y nadie a quien
-- preguntarle qué se capturó cuando la factura no cuadre. Y al revés: una firma
-- colgada de un borrador diría que alguien envió lo que nadie envió.
--
-- Es el mismo par que `ck_renglon_descarte`, `ck_renglon_ajuste` y
-- `ck_renglon_eleccion`, y se comprueba igual que ellos: que la restricción
-- exista y que las dos columnas estén.
(28,
 'El envío va firmado: quién y cuándo, pareados con el estado',
 'la restricción y las dos columnas',
 (SELECT CASE
           WHEN NOT EXISTS (SELECT 1 FROM pg_constraint con
                             WHERE con.conrelid = to_regclass('pedidos.pedido')
                               AND con.conname = 'ck_pedido_envio')
                THEN 'NO EXISTE ck_pedido_envio'
           WHEN (SELECT count(*) FROM pg_attribute a
                  WHERE a.attrelid = to_regclass('pedidos.pedido')
                    AND NOT a.attisdropped
                    AND a.attname IN ('enviado_por', 'enviado_en')) <> 2
                THEN 'falta enviado_por o enviado_en'
           ELSE 'la restricción y las dos columnas'
         END),
 NULL),

-- LA MARCA DE CAPTURA, PAREADA (ticket 22, ADR 0010). Tachar un renglón en la
-- pantalla de captura es la palabra de una persona sobre lo que tecleó en un
-- portal que Continental no ve: sin su firma, "ya se capturó" queda en voz
-- pasiva y no hay a quién preguntarle qué se tecleó cuando la factura no
-- cuadre. Y sin las DOS columnas en la base -- si la migración 0007 no se
-- corrió-- la primera lectura de la lista rebota en atlas con "column
-- capturado_por does not exist", porque `_LEER_RENGLONES` las nombra.
--
-- Es la misma forma que la 28 y se comprueba igual: que la restricción exista
-- y que las dos columnas estén.
(29,
 'La marca de captura va firmada: quién y cuándo, pareados',
 'la restricción y las dos columnas',
 (SELECT CASE
           WHEN NOT EXISTS (SELECT 1 FROM pg_constraint con
                             WHERE con.conrelid = to_regclass('pedidos.renglon')
                               AND con.conname = 'ck_renglon_captura')
                THEN 'NO EXISTE ck_renglon_captura'
           WHEN (SELECT count(*) FROM pg_attribute a
                  WHERE a.attrelid = to_regclass('pedidos.renglon')
                    AND NOT a.attisdropped
                    AND a.attname IN ('capturado_por', 'capturado_en')) <> 2
                THEN 'falta capturado_por o capturado_en'
           ELSE 'la restricción y las dos columnas'
         END),
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
        || 'conocido(s). El rol escribe sus cinco tablas, lee las cinco de '
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
