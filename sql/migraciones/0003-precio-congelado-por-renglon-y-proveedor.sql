-- 0003 - el esquema `pedidos` gana una CUARTA tabla,
-- `pedidos.precio_de_proveedor`: el precio congelado de un renglón en un
-- proveedor, con el instante de la lectura (ticket 12).
--
-- SE CORRE A MANO, UNA VEZ, CON CREDENCIALES DE DUEÑO, igual que
-- `sql/crear_tablas.sql` y las migraciones 0001 y 0002, y por la misma razón
-- (ADR 0003): esto es DDL, y el rol `continental` no puede hacer DDL a
-- propósito. **No lo corre el servicio, no lo corre una prueba y no lo corre
-- el lote de la noche.** Si algún día el código de arranque aplicara
-- migraciones solo, el rol necesitaría CREATE sobre su esquema -- y con CREATE
-- puede crear tablas que él mismo posee, que es la mitad silenciosa que el ADR
-- 0003 existe para impedir.
--
-- Desde `~/proyectos/Continental` en atlas:
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 \
--       < sql/migraciones/0003-precio-congelado-por-renglon-y-proveedor.sql
--
-- `<` y no `-f`: con `docker exec`, el `-f` de psql busca el archivo DENTRO
-- del contenedor, donde este repo no está montado. `ON_ERROR_STOP=1` porque
-- sin él psql sigue tras un error y termina diciendo que todo salió bien.
--
--
-- ## DESPUÉS DE ESTO HAY QUE VOLVER A CORRER `sql/crear_rol.sql`
--
-- Y aquí esta migración se aparta de las dos anteriores, así que conviene
-- leerlo dos veces. Las 0001 y 0002 agregaban COLUMNAS, y el
-- `GRANT SELECT, INSERT, UPDATE` es sobre la tabla entera: cubría las columnas
-- nuevas sin tocar nada. Ésta crea una TABLA, y **un permiso no se puede dar
-- sobre una tabla que todavía no existe**: el GRANT que `crear_rol.sql` corrió
-- en su día no la alcanza, porque no estaba.
--
-- Si se salta este paso, todo se ve bien hasta el primer clic en "Consultar
-- precio" en atlas, que rebota con:
--
--     ERROR:  permission denied for table precio_de_proveedor
--
-- y lo hace DENTRO del hilo que consulta, así que la pantalla solo diría "no
-- se pudo guardar el precio" mientras el detalle vive en la bitácora
-- (regla 5). `crear_rol.sql` es idempotente y volverlo a correr no le toca la
-- contraseña a un rol que ya existe, así que el paso es barato:
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 -v password="'LA_DEL_.ENV'" < sql/crear_rol.sql
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 < sql/verificar_rol.sql ; echo "salida: $?"
--
-- La comprobación 4 del verificador espera **cuatro** tablas desde este
-- ticket, y la 6 pregunta si al rol le falta algún permiso sobre alguna de
-- ellas: las dos cazan este olvido.
--
--
-- ## Qué guarda, y por qué es una tabla y no columnas en `renglon`
--
-- El grano es (renglón, proveedor): una visita a un portal con una clave
-- devuelve el precio y la existencia de ese producto en ese proveedor, y eso
-- es una fila. En columnas serían cuatro proveedores por nueve datos -treinta
-- y seis columnas con el nombre de un proveedor dentro-, y "contra cuántos
-- proveedores se comparó este renglón" -- que es lo que el ticket 15 cuenta --
-- se volvería un CASE de nueve columnas en vez de un count(*).
--
-- Guarda cuatro cosas que el ticket pide con todas sus letras:
--
--   - el precio COMO LLEGÓ (`precio_como_llego`, texto) y el número al que se
--     pudo convertir (`precio`, numeric(12,2), NUNCA coma flotante),
--   - la existencia que reportó el proveedor, también con su texto original,
--   - el INSTANTE de la lectura (`consultado_en`, con DEFAULT now()),
--   - y el MOTIVO cuando no hay precio. Un precio faltante no es un NULL mudo:
--     "la sesión caducó" lo arregla el encargado en dos clics y "no está en
--     ese catálogo" no lo arregla nadie, y sin el motivo los dos se ven igual.
--
--
-- ## ESTA TABLA SOLO CRECE
--
-- Sin UNIQUE sobre (renglón, proveedor) y sin un solo UPDATE en el código. Una
-- segunda consulta del mismo renglón AGREGA. Con UPDATE, una consulta fallida
-- borraría un precio bueno -- se consulta a las 8 y NADRO da $86.05, a las 9
-- la sesión ya caducó, y el $86.05 se vuelve un hueco: se habría perdido el
-- dato por intentar mejorarlo--. El porqué entero está en `crear_tablas.sql`,
-- junto a la definición.
--
--
-- ## Es idempotente
--
-- `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, y
-- `DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT` para los CHECK, porque
-- `ADD CONSTRAINT` no tiene `IF NOT EXISTS` en Postgres. Quitar y volver a
-- poner tiene además una propiedad que conviene: el CHECK que queda es el de
-- este archivo, aunque alguien hubiera creado otro con el mismo nombre y otra
-- definición -- que es exactamente el caso que `CREATE TABLE IF NOT EXISTS`
-- deja pasar callado.
--
-- Quitar un CHECK no borra una sola fila. Se hace con credenciales de dueño y
-- en una transacción: si el ADD fallara -- porque ya hay filas que lo violan--
-- el DROP se va con él y la tabla se queda como estaba.

SET client_encoding TO 'UTF8';

-- Que no lo corra quien no debe, igual que `crear_tablas.sql` y las dos
-- migraciones anteriores. Con el rol acotado esto fallaría por permisos, pero
-- el mensaje de Postgres no diría cuál es la manera correcta de correrlo -- y
-- aquí importa más que nunca: si alguien le hubiera dado CREATE al rol, esto
-- no fallaría, crearía la tabla A NOMBRE DE `continental`, y el rol podría
-- alterarla y borrarla. La casilla "el rol acotado no puede crear tablas"
-- seguiría viéndose verde en el archivo de permisos.
DO $guardia$
BEGIN
    IF current_user = 'continental' THEN
        RAISE EXCEPTION '%',
            'Esta migración se corre con credenciales de DUEÑO (usuario '
            || 'farmacia), no con el rol acotado continental: las tablas de '
            || 'pedidos las posee el dueño, y quien posee una tabla puede '
            || 'alterarla y borrarla (ADR 0003).';
    END IF;
END
$guardia$;

-- Y que no se corra antes de tiempo: esta tabla le apunta a `pedidos.renglon`
-- con una llave foránea, y sin ella el CREATE fallaría con un mensaje que no
-- dice cuál es el orden correcto.
DO $orden$
BEGIN
    IF to_regclass('pedidos.renglon') IS NULL THEN
        RAISE EXCEPTION '%',
            'No existe pedidos.renglon, y esta tabla le apunta con una llave '
            || 'foránea. Corre primero sql/crear_tablas.sql.';
    END IF;
END
$orden$;

BEGIN;

CREATE TABLE IF NOT EXISTS pedidos.precio_de_proveedor (
    precio_de_proveedor_id    bigint        GENERATED ALWAYS AS IDENTITY,
    negocio                   text          NOT NULL,
    renglon_id                bigint        NOT NULL,
    proveedor                 text          NOT NULL,
    consultado_en             timestamptz   NOT NULL DEFAULT now(),
    precio_como_llego         text,
    precio                    numeric(12,2),
    existencia_como_llego     text,
    existencia                numeric(12,3),
    motivo                    text,
    detalle                   text,
    clave_del_proveedor       text,
    descripcion_del_proveedor text,
    resultados                integer       NOT NULL DEFAULT 0,

    CONSTRAINT pk_precio_de_proveedor
        PRIMARY KEY (precio_de_proveedor_id),

    CONSTRAINT fk_precio_renglon
        FOREIGN KEY (renglon_id, negocio)
        REFERENCES pedidos.renglon (renglon_id, negocio)
);

-- Los CHECK se aplican aparte del CREATE y con DROP + ADD, para que el archivo
-- sea idempotente DE VERDAD: sobre una base donde la tabla ya existe con otra
-- forma, el `CREATE TABLE IF NOT EXISTS` de arriba calla, y sin esto los CHECK
-- de esa tabla vieja se quedarían puestos sin que nadie se entere.

ALTER TABLE pedidos.precio_de_proveedor
    DROP CONSTRAINT IF EXISTS ck_precio_negocio;
ALTER TABLE pedidos.precio_de_proveedor
    ADD CONSTRAINT ck_precio_negocio CHECK (negocio <> '');

-- Sin saber quién dio el precio, el precio no sirve para nada.
ALTER TABLE pedidos.precio_de_proveedor
    DROP CONSTRAINT IF EXISTS ck_precio_proveedor;
ALTER TABLE pedidos.precio_de_proveedor
    ADD CONSTRAINT ck_precio_proveedor CHECK (proveedor <> '');

-- EL CERO ES EL ÚNICO NÚMERO QUE AQUÍ PUEDE HACER DAÑO: gana toda comparación
-- de "el más barato" y dispara la compra equivocada (regla 4 de CLAUDE.md).
-- Un "0.00" que escriba un portal tampoco es un regalo: es un portal que no
-- supo decir cuánto cuesta. El porqué completo está en `crear_tablas.sql`.
ALTER TABLE pedidos.precio_de_proveedor
    DROP CONSTRAINT IF EXISTS ck_precio_positivo;
ALTER TABLE pedidos.precio_de_proveedor
    ADD CONSTRAINT ck_precio_positivo CHECK (precio > 0);

-- Un proveedor no tiene menos que cero. La existencia negativa SÍ es real en
-- `renglon.existencia` -SICAR la permite- y eso es lo nuestro; esto es lo que
-- reporta el portal de otro.
ALTER TABLE pedidos.precio_de_proveedor
    DROP CONSTRAINT IF EXISTS ck_precio_existencia;
ALTER TABLE pedidos.precio_de_proveedor
    ADD CONSTRAINT ck_precio_existencia CHECK (existencia >= 0);

ALTER TABLE pedidos.precio_de_proveedor
    DROP CONSTRAINT IF EXISTS ck_precio_resultados;
ALTER TABLE pedidos.precio_de_proveedor
    ADD CONSTRAINT ck_precio_resultados CHECK (resultados >= 0);

-- UN PRECIO FALTANTE NO ES UN NULL MUDO, en los dos sentidos: ni un NULL
-- callado, ni un motivo colgado en una lectura que sí trajo precio -- el
-- segundo haría que el conteo del ticket 15 contara huecos que no existen.
ALTER TABLE pedidos.precio_de_proveedor
    DROP CONSTRAINT IF EXISTS ck_precio_sin_dato;
ALTER TABLE pedidos.precio_de_proveedor
    ADD CONSTRAINT ck_precio_sin_dato
        CHECK ((precio IS NULL) = (motivo IS NOT NULL));

-- El vocabulario cerrado de `precios.MOTIVOS`, con el mismo texto exacto.
-- LOS ACENTOS VIAJAN DENTRO DEL CHECK, igual que el de 'en tránsito': si psql
-- manda este archivo como latin1, el primer INSERT con motivo rebota con una
-- violación de restricción que nadie sabría explicar. Por eso el SET
-- client_encoding de arriba, y por eso el archivo se imprime de vuelta abajo.
ALTER TABLE pedidos.precio_de_proveedor
    DROP CONSTRAINT IF EXISTS ck_precio_motivo_conocido;
ALTER TABLE pedidos.precio_de_proveedor
    ADD CONSTRAINT ck_precio_motivo_conocido
        CHECK (motivo IS NULL OR motivo IN (
            'sin resultados', 'varios resultados', 'no empareja',
            'el portal no contestó', 'la sesión caducó',
            'no se sabe leer la página', 'no alcanzó el tiempo',
            'precio ilegible'));

-- El texto original es la auditoría de la conversión: sin él, "¿de dónde salió
-- este 1234.50?" no tiene respuesta seis meses después.
ALTER TABLE pedidos.precio_de_proveedor
    DROP CONSTRAINT IF EXISTS ck_precio_con_su_texto;
ALTER TABLE pedidos.precio_de_proveedor
    ADD CONSTRAINT ck_precio_con_su_texto
        CHECK (precio IS NULL OR precio_como_llego IS NOT NULL);

-- La cadena vacía no existe, por la misma razón que en `ck_renglon_clave`: se
-- compara igual que un dato y empareja con cualquier otra vacía.
ALTER TABLE pedidos.precio_de_proveedor
    DROP CONSTRAINT IF EXISTS ck_precio_textos;
ALTER TABLE pedidos.precio_de_proveedor
    ADD CONSTRAINT ck_precio_textos
        CHECK (precio_como_llego <> ''
               AND existencia_como_llego <> ''
               AND detalle <> ''
               AND clave_del_proveedor <> ''
               AND descripcion_del_proveedor <> '');

-- El índice es EXACTAMENTE el DISTINCT ON de `almacenamiento._LEER_PRECIOS`.
-- Esta tabla solo crece, así que sin él el costo de pintar la lista crece con
-- el historial de precios y no con lo que se está mirando.
CREATE INDEX IF NOT EXISTS ix_precio_ultimo
    ON pedidos.precio_de_proveedor
       (negocio, renglon_id, proveedor, consultado_en DESC);

COMMENT ON TABLE pedidos.precio_de_proveedor IS
    'Lo que un proveedor contestó de un renglón, CONGELADO, con el instante de '
    'la lectura. SOLO CRECE: una segunda consulta agrega filas y la '
    'comparación usa la más reciente por proveedor.';

COMMENT ON COLUMN pedidos.precio_de_proveedor.proveedor IS
    'La clave de Doyle: nadro, levic, vicma, quepharma (config/proveedores.yml '
    'de ese repo). Se guarda la clave y no el nombre porque la clave es lo que '
    'no cambia; cómo se escribe cada una vive en precios.NOMBRES_DE_PROVEEDOR.';

COMMENT ON COLUMN pedidos.precio_de_proveedor.consultado_en IS
    'Cuándo se leyó este precio, instante con zona. Los cuatro proveedores de '
    'una misma consulta lo comparten: fue una sola lectura.';

COMMENT ON COLUMN pedidos.precio_de_proveedor.precio IS
    'Precio de COMPRA, sin IVA, decimal explícito. NULL = sin dato, y entonces '
    'motivo dice por qué. Nunca cero.';

COMMENT ON COLUMN pedidos.precio_de_proveedor.precio_como_llego IS
    'El precio TAL CUAL lo escribió el portal ("1,234.50", a veces con $). Es '
    'lo único que permite auditar una conversión dudosa meses después.';

COMMENT ON COLUMN pedidos.precio_de_proveedor.existencia_como_llego IS
    'La existencia tal cual la escribió el portal. Los portales dicen "40", '
    '"+100" o "Disponible", y el texto vale cuando el número no: que la '
    'existencia no se pueda convertir NUNCA es motivo para tirar el precio.';

COMMENT ON COLUMN pedidos.precio_de_proveedor.motivo IS
    'Por qué NO hay precio, del vocabulario de precios.MOTIVOS. NULL cuando sí '
    'lo hay. Cada motivo lleva a una acción distinta: la sesión caducada la '
    'arregla el encargado en dos clics, "sin resultados" no la arregla nadie.';

COMMENT ON COLUMN pedidos.precio_de_proveedor.detalle IS
    'Lo que Doyle dijo, primera línea y acotado. Es un mensaje que Doyle '
    'redacta PARA QUE UNA PERSONA LO LEA (historia 23); lo que nunca viaja al '
    'navegador es el texto de una excepción nuestra (regla 5 de CLAUDE.md).';

COMMENT ON COLUMN pedidos.precio_de_proveedor.resultados IS
    'Cuántos resultados encontró el portal para esa clave. Es el dato con el '
    'que el ticket 13 decide VICMA.';

COMMENT ON COLUMN pedidos.precio_de_proveedor.descripcion_del_proveedor IS
    'Cómo describe el portal el producto de esta fila. Evidencia de que se '
    'comparó lo mismo.';

COMMIT;


-- --------------------------------------------------------------------------
-- Qué quedó
-- --------------------------------------------------------------------------
--
-- Se imprime en vez de darse por hecho, igual que en la 0001 y la 0002: un
-- CHECK puede entrar con el acento deformado y verse impecable en el archivo.

SELECT a.attname                            AS columna,
       format_type(a.atttypid, a.atttypmod) AS tipo,
       NOT a.attnotnull                     AS admite_nulos
  FROM pg_attribute a
 WHERE a.attrelid = to_regclass('pedidos.precio_de_proveedor')
   AND a.attnum > 0
   AND NOT a.attisdropped
 ORDER BY a.attnum;

SELECT con.conname                   AS restriccion,
       pg_get_constraintdef(con.oid) AS definicion
  FROM pg_constraint con
 WHERE con.conrelid = to_regclass('pedidos.precio_de_proveedor')
 ORDER BY con.conname;

SELECT pg_get_userbyid(c.relowner) AS propietario
  FROM pg_class c
 WHERE c.oid = to_regclass('pedidos.precio_de_proveedor');

\echo ''
\echo '>> Arriba deben salir 14 columnas y el CHECK de motivos CON SUS ACENTOS.'
\echo '>> Si dice "el portal no contesto" sin acento, psql mando el archivo en'
\echo '>> latin1 y el primer INSERT con motivo va a rebotar. Vuelve a correrlo.'
\echo '>> El propietario TIENE que ser farmacia, nunca continental.'
\echo ''
\echo '>> FALTA UN PASO, Y SIN EL NADA DE ESTO SIRVE:'
\echo '>>   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \'
\echo '>>       -v ON_ERROR_STOP=1 -v password="LA_DEL_ENV" < sql/crear_rol.sql'
\echo '>> Un GRANT no se puede dar sobre una tabla que no existia. Sin esto, el'
\echo '>> primer precio rebota con "permission denied for table'
\echo '>> precio_de_proveedor". Despues, sql/verificar_rol.sql da el veredicto.'
