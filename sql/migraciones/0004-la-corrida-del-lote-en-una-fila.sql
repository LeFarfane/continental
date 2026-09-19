-- 0004 - el esquema `pedidos` gana una QUINTA tabla,
-- `pedidos.corrida_del_lote`: cómo le fue al lote nocturno UNA noche, con
-- grano de UNA FILA POR CORRIDA (ticket 19, ADR 0007).
--
-- SE CORRE A MANO, UNA VEZ, CON CREDENCIALES DE DUEÑO, igual que
-- `sql/crear_tablas.sql` y las migraciones 0001 a 0003, y por la misma razón
-- (ADR 0003): esto es DDL, y el rol `continental` no puede hacer DDL a
-- propósito. **No lo corre el servicio, no lo corre una prueba y no lo corre
-- el lote de la noche.** Si algún día el código de arranque aplicara
-- migraciones solo, el rol necesitaría CREATE sobre su esquema -- y con CREATE
-- puede crear tablas que él mismo posee, que es la mitad silenciosa que el ADR
-- 0003 existe para impedir.
--
-- Desde `~/proyectos/Continental` en atlas -- **plano, no anidado**: en atlas
-- los repos son hermanos (`~/proyectos/Marlowe`, y `~/proyectos/Farmacia`, que
-- es farmacia-data), al revés que en la torre--:
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 \
--       < sql/migraciones/0004-la-corrida-del-lote-en-una-fila.sql
--
-- `<` y no `-f`: con `docker exec`, el `-f` de psql busca el archivo DENTRO
-- del contenedor, donde este repo no está montado. `ON_ERROR_STOP=1` porque
-- sin él psql sigue tras un error y termina diciendo que todo salió bien.
--
--
-- ## DESPUÉS DE ESTO HAY QUE VOLVER A CORRER `sql/crear_rol.sql`
--
-- Es el mismo paso que exigió la 0003 y por la misma razón, así que conviene
-- no darlo por sabido: **un permiso no se puede dar sobre una tabla que
-- todavía no existe**. El `GRANT` que `crear_rol.sql` corrió en su día no
-- alcanza a ésta, porque no estaba. Las migraciones 0001 y 0002 no lo exigían
-- -- agregaban COLUMNAS, y el GRANT es sobre la tabla entera--, y es justo esa
-- diferencia la que hace fácil olvidarlo.
--
-- Si se salta este paso, **todo se ve bien hasta las 22:00**, que es cuando el
-- lote corre sin nadie mirando. Y entonces falla así:
--
--     ERROR:  permission denied for table corrida_del_lote
--
-- La corrida NO se aborta por eso -- la escritura va en su propio `try` dentro
-- del `finally`, ADR 0007-- así que los precios de esa noche se guardan igual
-- y el journal lo dice. Lo que se pierde es la pantalla: a la mañana va a
-- decir *"el lote no corrió sobre esta lista"* sobre una noche en la que sí
-- corrió, porque es exactamente la AUSENCIA de esa fila lo que significa eso.
-- Un permiso que falta leído como un lote que no corrió: el tipo de falla que
-- este repo persigue.
--
-- `crear_rol.sql` es idempotente y volverlo a correr no le toca la contraseña
-- a un rol que ya existe, así que el paso es barato:
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 -v password="'LA_DEL_.ENV'" < sql/crear_rol.sql
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 < sql/verificar_rol.sql ; echo "salida: $?"
--
-- La comprobación 4 del verificador espera **cinco** tablas desde este ticket,
-- y la 6 pregunta si al rol le falta algún permiso sobre alguna de ellas: las
-- dos cazan este olvido. La 16 también, de otra manera: cuenta las llaves de
-- identidad y las compara contra el número de tablas del esquema.
--
--
-- ## Qué guarda, y por qué UNA fila por noche y no cuatro por renglón
--
-- El ADR 0007 lo razona entero, con las dos opciones descartadas. Lo corto:
--
-- La primera casilla del ticket 19 pide que la pantalla distinga tres motivos
-- -- *el lote se cortó por tiempo*, *el portal no contestó*, *la sesión
-- caducó*--. Los dos últimos ya viven en `precio_de_proveedor.motivo` desde el
-- ticket 12. El primero no vivía en ningún lado, porque el ticket 18 decidió
-- que un renglón al que el tope no alcanzó **no deja fila** (ADR 0006).
--
-- La tentación era escribir esas filas de todos modos: cuatro por renglón no
-- alcanzado, con motivo 'no alcanzó el tiempo'. Se descartó por dos razones, y
-- la primera es la que la hunde:
--
--   1. **Habría que inventarse a qué proveedores se le iba a preguntar.** Esa
--      lista sale del acuse de Doyle, y a un renglón que no se consultó no
--      hubo acuse que darle (hilo abierto 3 de `HANDOVER.md`). Escribir "le
--      preguntamos a NADRO y no contestó a tiempo" cuando a NADRO no se le
--      preguntó es escribir un hecho que no ocurrió: la misma prohibición que
--      el cero inventado (regla 4 de CLAUDE.md).
--   2. Dispararía la condición de revisión del ADR 0004: una noche que corte
--      al 20% dejaría ~11,000 filas de puro hueco.
--
-- Así que lo que se guarda es **el resumen de la corrida**, que el lote ya
-- calculaba y tiraba: `en_la_lista`, `consultados`, `con_precio`,
-- `sin_alcanzar`, `no_se_pudo`, `sin_clave`, el `final` y si el orden se
-- cumplió. La pantalla lee esa fila junto con la lista y de ahí deduce, por
-- renglón, cuál de los seis motivos le toca (`faltantes.por_que_no_hay_lectura`,
-- que es una función pura con su tabla de casos y sin Postgres).
--
-- **Lo que se renuncia:** se guarda CUÁNTOS quedaron sin alcanzar, no CUÁLES.
-- Hay una noche en la que la deducción no es segura -- la que cortó por tope Y
-- ADEMÁS tuvo renglones `no_se_pudo`--, y ahí la pantalla escribe
-- "probablemente" con el otro número al lado en vez de elegir a cara o cruz.
--
--
-- ## ESTA TABLA SOLO CRECE
--
-- Sin UNIQUE y sin un solo UPDATE en el código: una corrida es un hecho del
-- pasado, y la de anoche no se corrige porque hoy haya otra. Cinco filas por
-- semana -- el timer es `OnCalendar=Mon-Fri 22:00`, sin `Persistent=true`
-- (ADR 0006)--, con una decena de columnas de enteros. La tabla del precio
-- crece ~4xN por noche; ésta crece 1.
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

-- Que no lo corra quien no debe, igual que `crear_tablas.sql` y las tres
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

-- Y que no se corra antes de tiempo: esta tabla le apunta a
-- `pedidos.pedido_sugerido` con una llave foránea, y sin ella el CREATE
-- fallaría con un mensaje que no dice cuál es el orden correcto.
DO $orden$
BEGIN
    IF to_regclass('pedidos.pedido_sugerido') IS NULL THEN
        RAISE EXCEPTION '%',
            'No existe pedidos.pedido_sugerido, y esta tabla le apunta con una '
            || 'llave foránea. Corre primero sql/crear_tablas.sql.';
    END IF;
END
$orden$;

BEGIN;

CREATE TABLE IF NOT EXISTS pedidos.corrida_del_lote (
    corrida_del_lote_id bigint        GENERATED ALWAYS AS IDENTITY,
    negocio             text          NOT NULL,
    pedido_sugerido_id  bigint,
    fecha_del_pedido    date,
    termino_en          timestamptz   NOT NULL DEFAULT now(),
    final               text          NOT NULL,
    segundos            numeric(10,1) NOT NULL DEFAULT 0,
    tope_minutos        numeric(10,1) NOT NULL DEFAULT 0,
    en_la_lista         integer       NOT NULL DEFAULT 0,
    consultados         integer       NOT NULL DEFAULT 0,
    con_precio          integer       NOT NULL DEFAULT 0,
    sin_alcanzar        integer       NOT NULL DEFAULT 0,
    no_se_pudo          integer       NOT NULL DEFAULT 0,
    sin_clave           integer       NOT NULL DEFAULT 0,
    orden_cumplido      boolean       NOT NULL DEFAULT false,
    detalle             text,

    CONSTRAINT pk_corrida_del_lote
        PRIMARY KEY (corrida_del_lote_id),

    -- ADMITE NULOS, y eso es lo que la distingue de la llave foránea del
    -- precio: una corrida sin lista SÍ se guarda -- es justo la que contesta
    -- "el lote corrió y no encontró ventas"--. En Postgres una llave foránea
    -- compuesta con MATCH SIMPLE -el de omisión- no se comprueba cuando alguna
    -- de sus columnas es nula, así que esas filas entran sin apuntar a nada.
    CONSTRAINT fk_corrida_lista
        FOREIGN KEY (pedido_sugerido_id, negocio)
        REFERENCES pedidos.pedido_sugerido (pedido_sugerido_id, negocio)
);

-- Los CHECK se aplican aparte del CREATE y con DROP + ADD, para que el archivo
-- sea idempotente DE VERDAD: sobre una base donde la tabla ya existe con otra
-- forma, el `CREATE TABLE IF NOT EXISTS` de arriba calla, y sin esto los CHECK
-- de esa tabla vieja se quedarían puestos sin que nadie se entere.

ALTER TABLE pedidos.corrida_del_lote
    DROP CONSTRAINT IF EXISTS ck_corrida_negocio;
ALTER TABLE pedidos.corrida_del_lote
    ADD CONSTRAINT ck_corrida_negocio CHECK (negocio <> '');

-- EL VOCABULARIO CERRADO DE `almacenamiento.FINALES_DE_LA_CORRIDA`, con el
-- mismo texto exacto. Cerrado y no texto libre por la misma razón que los
-- ocho motivos del precio, y aquí pesa más: LA PANTALLA DECIDE CON ESTE VALOR
-- qué frase le pone a cada renglón sin lectura. Un quinto valor metido sin
-- migración no se vería como un error: se leería como "el lote no corrió".
--
-- LOS ACENTOS VIAJAN DENTRO DEL CHECK. Si psql manda este archivo como latin1,
-- el primer INSERT del lote rebota a las 22:00 con una violación de
-- restricción que nadie sabría explicar -- y el lote es justamente lo que
-- corre sin nadie mirando--. Por eso el SET client_encoding de arriba, y por
-- eso el archivo se imprime de vuelta abajo.
ALTER TABLE pedidos.corrida_del_lote
    DROP CONSTRAINT IF EXISTS ck_corrida_final;
ALTER TABLE pedidos.corrida_del_lote
    ADD CONSTRAINT ck_corrida_final
        CHECK (final IN (
            'terminó', 'se acabó el tiempo', 'se interrumpió', 'no hubo lista'));

-- UN CONTEO NEGATIVO NO ES "MENOS QUE NINGUNO", ES UN ERROR DE QUIEN CONTÓ.
-- Y estos números se pintan en la pantalla como "210 de 380": un negativo ahí
-- se lee como una pantalla rota, no como un dato.
ALTER TABLE pedidos.corrida_del_lote
    DROP CONSTRAINT IF EXISTS ck_corrida_conteos;
ALTER TABLE pedidos.corrida_del_lote
    ADD CONSTRAINT ck_corrida_conteos
        CHECK (en_la_lista  >= 0 AND consultados  >= 0
           AND con_precio   >= 0 AND sin_alcanzar >= 0
           AND no_se_pudo   >= 0 AND sin_clave    >= 0);

ALTER TABLE pedidos.corrida_del_lote
    DROP CONSTRAINT IF EXISTS ck_corrida_duracion;
ALTER TABLE pedidos.corrida_del_lote
    ADD CONSTRAINT ck_corrida_duracion
        CHECK (segundos >= 0 AND tope_minutos >= 0);

-- EL NUMERADOR NO PUEDE SER MAYOR QUE EL DENOMINADOR: es el par de números con
-- el que la pantalla escribe "el lote consultó 210 de 380 renglones".
ALTER TABLE pedidos.corrida_del_lote
    DROP CONSTRAINT IF EXISTS ck_corrida_consultados;
ALTER TABLE pedidos.corrida_del_lote
    ADD CONSTRAINT ck_corrida_consultados
        CHECK (consultados <= en_la_lista);

-- Un precio no llega de un renglón que no se consultó.
ALTER TABLE pedidos.corrida_del_lote
    DROP CONSTRAINT IF EXISTS ck_corrida_con_precio;
ALTER TABLE pedidos.corrida_del_lote
    ADD CONSTRAINT ck_corrida_con_precio
        CHECK (con_precio <= consultados);

-- LA LISTA Y SU FECHA VAN JUNTAS O NO VAN. Las dos son NULL en una corrida que
-- no llegó a abrir lista -'no hubo lista', o una que se cortó antes-, y eso es
-- NULO PORQUE NO HUBO, no porque no se sepa. Una corrida con fecha y sin lista
-- -o al revés- no se puede leer: la pantalla busca por id y escribiría la
-- fecha de otra noche.
ALTER TABLE pedidos.corrida_del_lote
    DROP CONSTRAINT IF EXISTS ck_corrida_lista;
ALTER TABLE pedidos.corrida_del_lote
    ADD CONSTRAINT ck_corrida_lista
        CHECK ((pedido_sugerido_id IS NULL) = (fecha_del_pedido IS NULL));

-- La cadena vacía no existe, por la misma razón que en `ck_renglon_clave`: se
-- compara igual que un dato y empareja con cualquier otra vacía.
ALTER TABLE pedidos.corrida_del_lote
    DROP CONSTRAINT IF EXISTS ck_corrida_detalle;
ALTER TABLE pedidos.corrida_del_lote
    ADD CONSTRAINT ck_corrida_detalle CHECK (detalle <> '');

-- El índice es EXACTAMENTE el `order by` de `almacenamiento._ULTIMA_CORRIDA`,
-- columna por columna y con el mismo DESC. La pantalla lo consulta en CADA
-- carga de la lista. Hoy la tabla tiene cinco filas por semana y un recorrido
-- completo costaría nada; está por la misma razón que el del precio y no por
-- el tamaño de hoy: es la tabla la que crece sin que nadie la pode, y el costo
-- de pintar la lista no debe crecer con el historial de corridas.
CREATE INDEX IF NOT EXISTS ix_corrida_ultima
    ON pedidos.corrida_del_lote
       (negocio, pedido_sugerido_id, termino_en DESC);

COMMENT ON TABLE pedidos.corrida_del_lote IS
    'Cómo le fue al lote nocturno UNA noche: una fila por corrida, no por '
    'renglón. SOLO CRECE. Es de donde la pantalla saca "el lote se cortó por '
    'tiempo antes de llegar a este renglón" (ADR 0007).';

COMMENT ON COLUMN pedidos.corrida_del_lote.termino_en IS
    'Cuándo acabó la corrida, instante con zona, puesto por la base.';

COMMENT ON COLUMN pedidos.corrida_del_lote.final IS
    'Cómo acabó, del vocabulario de almacenamiento.FINALES_DE_LA_CORRIDA. '
    '"se acabó el tiempo" NO es un error: detenerse al tope es lo que se le '
    'pide al lote. "se interrumpió" sí lo es, y lo que hay que mirar es el '
    'journal de esa noche.';

COMMENT ON COLUMN pedidos.corrida_del_lote.segundos IS
    'Cuánto duró la corrida, del reloj monótono del lote. También es el `ping` '
    'del latido a Uptime Kuma: una noche que empiece a tardar el doble se ve '
    'en esa gráfica antes de que nadie mire un journal.';

COMMENT ON COLUMN pedidos.corrida_del_lote.sin_alcanzar IS
    'Cuántos renglones quedaron FALTANTES POR TOPE. Cuántos, no cuáles: ese es '
    'el precio que el ADR 0007 pagó a cambio de una fila en vez de ~2,750.';

COMMENT ON COLUMN pedidos.corrida_del_lote.no_se_pudo IS
    'Cuántos se intentaron y no dejaron ni una fila guardada (Doyle no '
    'contestó al pedir la búsqueda). Mayor que cero es lo que vuelve INSEGURA '
    'la atribución por renglón: hay dos maneras de quedarse sin lectura esa '
    'noche y de un renglón concreto no se puede afirmar cuál le tocó.';

COMMENT ON COLUMN pedidos.corrida_del_lote.orden_cumplido IS
    'Si el recorrido fue en orden de importancia (clase ABC). Falso mientras '
    'marts.dim_producto no tenga la columna clase_abc (ADR 0018 de '
    'farmacia-data): el lote lo dice en vez de disimularlo.';

COMMIT;


-- --------------------------------------------------------------------------
-- Qué quedó
-- --------------------------------------------------------------------------
--
-- Se imprime en vez de darse por hecho, igual que en las tres anteriores: un
-- CHECK puede entrar con el acento deformado y verse impecable en el archivo.

SELECT a.attname                            AS columna,
       format_type(a.atttypid, a.atttypmod) AS tipo,
       NOT a.attnotnull                     AS admite_nulos
  FROM pg_attribute a
 WHERE a.attrelid = to_regclass('pedidos.corrida_del_lote')
   AND a.attnum > 0
   AND NOT a.attisdropped
 ORDER BY a.attnum;

SELECT con.conname                   AS restriccion,
       pg_get_constraintdef(con.oid) AS definicion
  FROM pg_constraint con
 WHERE con.conrelid = to_regclass('pedidos.corrida_del_lote')
 ORDER BY con.conname;

SELECT pg_get_userbyid(c.relowner) AS propietario
  FROM pg_class c
 WHERE c.oid = to_regclass('pedidos.corrida_del_lote');

\echo ''
\echo '>> Arriba deben salir 16 columnas y el CHECK de ck_corrida_final CON SUS'
\echo '>> ACENTOS: termino, se acabo el tiempo, se interrumpio. Si salen sin'
\echo '>> acento, psql mando el archivo en latin1 y el primer INSERT del lote va'
\echo '>> a rebotar a las 22:00, sin nadie mirando. Vuelve a correrlo.'
\echo '>> El propietario TIENE que ser farmacia, nunca continental.'
\echo ''
\echo '>> FALTA UN PASO, Y SIN EL NADA DE ESTO SIRVE:'
\echo '>>   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \'
\echo '>>       -v ON_ERROR_STOP=1 -v password="LA_DEL_ENV" < sql/crear_rol.sql'
\echo '>> Un GRANT no se puede dar sobre una tabla que no existia. Sin esto, el'
\echo '>> lote de las 22:00 rebota con "permission denied for table'
\echo '>> corrida_del_lote" y a la manana la pantalla dice "el lote no corrio"'
\echo '>> sobre una noche en la que si corrio. Despues, sql/verificar_rol.sql.'
