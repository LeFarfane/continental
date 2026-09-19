-- 0005 - elegir proveedor por renglón y partir el sugerido en pedidos
-- (ticket 20, ADR 0008).
--
-- NO CREA NINGUNA TABLA: el esquema `pedidos` sigue teniendo CINCO. Lo que
-- hace son cinco cosas sobre las que ya están:
--
--   1. `pedidos.pedido` gana `proveedor` (la clave de Doyle) y `estado`.
--   2. `pedidos.pedido.proveedor_id` pasa a ADMITIR NULOS.
--   3. `ux_pedido_proveedor` se mueve de `proveedor_id` a `proveedor`.
--   4. `pedidos.renglon` gana `proveedor_elegido`, `elegido_por` y
--      `elegido_en`, con su CHECK pareado.
--   5. `fk_renglon_pedido` pasa a llevar también `pedido_sugerido_id`.
--
-- SE CORRE A MANO, UNA VEZ, CON CREDENCIALES DE DUEÑO, igual que
-- `sql/crear_tablas.sql` y las migraciones 0001 a 0004, y por la misma razón
-- (ADR 0003): esto es DDL, y el rol `continental` no puede hacer DDL a
-- propósito. **No lo corre el servicio, no lo corre una prueba y no lo corre
-- el lote de la noche.** Si algún día el código de arranque aplicara
-- migraciones solo, el rol necesitaría ALTER sobre sus tablas -- y con ALTER
-- puede quitar un CHECK, que es la mitad de las garantías de este esquema.
--
-- Desde `~/proyectos/Continental` en atlas -- **plano, no anidado**: en atlas
-- los repos son hermanos (`~/proyectos/Marlowe`, y `~/proyectos/Farmacia`, que
-- es farmacia-data), al revés que en la torre--:
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 \
--       < sql/migraciones/0005-elegir-proveedor-y-partir.sql
--
-- `<` y no `-f`: con `docker exec`, el `-f` de psql busca el archivo DENTRO
-- del contenedor, donde este repo no está montado. `ON_ERROR_STOP=1` porque
-- sin él psql sigue tras un error y termina diciendo que todo salió bien.
--
--
-- ## `sql/crear_rol.sql` NO hace falta volver a correrlo
--
-- Al revés que las migraciones 0003 y 0004, que estrenaban una TABLA: aquí
-- solo se agregan columnas y se cambian restricciones, y el
-- `GRANT SELECT, INSERT, UPDATE` es sobre la tabla entera -- no se usan
-- permisos por columna, a propósito--. Es la misma diferencia que las 0001 y
-- 0002 documentaron, dicha al revés para que no haya que deducirla.
--
-- Lo que SÍ conviene correr después es `sql/verificar_rol.sql`: sus
-- comprobaciones 23 a 26 son nuevas y leen DE VUELTA, desde el catálogo, las
-- tres cosas que esta migración cambia -- que `proveedor_id` admita nulos, que
-- `ux_pedido_proveedor` haya quedado sobre la clave de Doyle, y que
-- `fk_renglon_pedido` lleve las tres columnas--. Las tres se pueden ver bien en
-- este archivo y estar mal en la base.
--
--
-- ## EL PUENTE QUE ESTA MIGRACIÓN ABRE, Y POR QUÉ HACÍA FALTA
--
-- Hasta aquí la comparación (tickets 12-15) hablaba en **claves de Doyle**
-- -`nadro`, `levic`, `vicma`, `quepharma`: es lo que guarda
-- `precio_de_proveedor.proveedor`- y `pedidos.pedido` hablaba en **`pro_id` de
-- SICAR** (`marts.dim_proveedor.proveedor_id`). **Nada las cruzaba**: ni el
-- YAML, ni el código, ni el DDL.
--
-- La decisión del ADR 0008, en una frase: **la identidad del pedido es la
-- clave de Doyle, y el `proveedor_id` de SICAR es una correspondencia que
-- puede faltar.** Se le pide a quien se le preguntó el precio.
--
-- Por eso `proveedor_id` pasa a admitir nulos, y NO es un aflojamiento: es un
-- hecho medido. `marts.dim_proveedor` tiene 22 filas en atlas (leído el
-- 2026-09-19) -- NADRO es el 1, VICMA el 8, LEVIC el 10-- y **QuePharma no
-- está**: la farmacia nunca le ha comprado, así que SICAR no tiene una fila
-- suya. Con `NOT NULL`, pedirle a QuePharma sería imposible o habría que
-- inventarle un id, que es lo que la regla 4 de CLAUDE.md prohíbe.
--
-- El mapa clave -> `pro_id` vive en `config/continental.yml`, bajo
-- `pedido.proveedores_en_sicar`, y se lee en `src/continental/proveedores.py`.
-- Guarda el ID y no el nombre a propósito: **el `pro_id` no cambia cuando
-- SICAR renombra**, y un puente por nombre se rompería con el primer acento
-- corregido.
--
--
-- ## Y POR ESO `ux_pedido_proveedor` TIENE QUE MOVERSE
--
-- Ésta es la mitad que se puede hacer mal sin que nada avise. La restricción
-- decía `UNIQUE (pedido_sugerido_id, proveedor_id)` y sostenía "un pedido
-- sugerido se reparte en varios pedidos, UNO POR PROVEEDOR". **En cuanto
-- `proveedor_id` admite nulos deja de sostenerlo**: en Postgres dos nulos no
-- se consideran iguales dentro de un UNIQUE, así que dos pedidos a QuePharma
-- -- los dos con `proveedor_id` en NULL-- entrarían los dos, sin un solo error
-- que ver. La garantía tiene que estar sobre la columna que siempre vale algo,
-- que es la clave de Doyle.
--
-- Conserva el nombre porque sigue significando lo mismo, y porque
-- `almacenamiento._ABRIR_EL_PEDIDO` la nombra en su
-- `ON CONFLICT ON CONSTRAINT`: eso es lo que hace que partir dos veces
-- reencuentre el pedido que ya estaba en vez de duplicarlo.
--
--
-- ## LA OTRA RESTRICCIÓN QUE SE APRIETA: `fk_renglon_pedido`
--
-- "Un renglón pertenece a un solo pedido" ya lo defendía la tabla -- es UNA
-- columna con UNA llave foránea, no una tabla de cruce--. Lo que le faltaba es
-- que el pedido fuera de **esta** lista: con `(pedido_id, negocio)`, un
-- renglón de la lista del martes podía colgar de un pedido de la del lunes, la
-- restricción se cumplía, y el total de ese pedido contaba mercancía de otro
-- día. Ahora la llave lleva `pedido_sugerido_id` y apunta a
-- `ux_pedido_de_la_lista`, que esta migración crea para ella.
--
--
-- ## Por qué existe este archivo y no basta con `crear_tablas.sql`
--
-- Se editó `crear_tablas.sql` **también**, y las dos cosas son necesarias. La
-- regla vive en el ADR 0003, en sus Consecuencias: `CREATE TABLE IF NOT
-- EXISTS` **calla si la tabla ya existe con otra forma**, así que sobre la
-- base de atlas volver a correrlo no agrega nada y no avisa -- el primer
-- `INSERT INTO pedidos.pedido (..., proveedor, ...)` rebotaría con "column
-- proveedor of relation pedido does not exist"--; y dejar las columnas solo
-- aquí haría que una base desde cero naciera sin ellas.
--
--
-- ## Es idempotente
--
-- Correrlo dos veces no rompe nada y no cambia nada la segunda vez, igual que
-- las cuatro anteriores y sin tabla de migraciones aplicadas: lo que protege
-- es que cada sentencia sea idempotente por sí misma. `ADD COLUMN IF NOT
-- EXISTS` para las columnas; `DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT`
-- para las restricciones, porque `ADD CONSTRAINT` no tiene `IF NOT EXISTS` en
-- Postgres. Quitar y volver a poner tiene además una propiedad que conviene:
-- la restricción que queda es la de este archivo, aunque alguien hubiera
-- creado otra con el mismo nombre y otra definición.
--
-- Quitar una restricción no borra una sola fila. Se hace con credenciales de
-- dueño y en una transacción: si el `ADD` fallara -- porque ya hay filas que la
-- violan-- el `DROP` se va con él y la tabla se queda como estaba.

SET client_encoding TO 'UTF8';

-- Que no lo corra quien no debe, igual que `crear_tablas.sql` y las cuatro
-- migraciones anteriores. Con el rol acotado esto fallaría por permisos, pero
-- el mensaje de Postgres no diría cuál es la manera correcta de correrlo.
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
-- 1) `pedidos.pedido` gana `proveedor` y `estado`
-- --------------------------------------------------------------------------

-- Entra NULLable y se aprieta abajo. `ADD COLUMN ... NOT NULL` sin DEFAULT
-- fallaría sobre una tabla con filas, y con un DEFAULT inventaría un proveedor
-- para pedidos que ya existieran -- que es exactamente lo que no queremos que
-- pase en silencio.
ALTER TABLE pedidos.pedido
    ADD COLUMN IF NOT EXISTS proveedor text;

-- HOY ESTA TABLA ESTÁ VACÍA EN ATLAS y es un hecho verificable, no una
-- suposición: hasta el ticket 20 **ningún código escribía en ella**. El
-- `SELECT` de abajo lo comprueba en vez de darlo por bueno, y si alguien
-- hubiera metido filas a mano el mensaje dice qué hacer en vez de dejar un
-- `SET NOT NULL` rebotando con "column contains null values", que no explica
-- nada.
DO $sin_proveedor$
DECLARE
    huerfanos bigint;
BEGIN
    SELECT count(*) INTO huerfanos
      FROM pedidos.pedido WHERE proveedor IS NULL;
    IF huerfanos > 0 THEN
        RAISE EXCEPTION '%',
            'Hay ' || huerfanos || ' pedido(s) sin `proveedor`. Esta tabla '
            || 'estaba vacía cuando se escribió el ticket 20 (ningún código '
            || 'escribía en ella todavía), así que alguien la llenó a mano. '
            || 'Ponles la clave de Doyle que les corresponda -- nadro, levic, '
            || 'vicma o quepharma-- y vuelve a correr esta migración. NO se '
            || 'rellena con un DEFAULT: inventar a quién se le pidió algo es '
            || 'peor que no saberlo (regla 4 de CLAUDE.md).';
    END IF;
END
$sin_proveedor$;

ALTER TABLE pedidos.pedido
    ALTER COLUMN proveedor SET NOT NULL;

-- `borrador` como DEFAULT porque es donde nace todo pedido, y las filas que
-- pudiera haber son borradores: nadie ha enviado nada, el ticket 21 todavía no
-- existe.
ALTER TABLE pedidos.pedido
    ADD COLUMN IF NOT EXISTS estado text NOT NULL DEFAULT 'borrador';

-- --------------------------------------------------------------------------
-- 2) `proveedor_id` pasa a admitir nulos
-- --------------------------------------------------------------------------
--
-- NULL = "SICAR no conoce a este proveedor", que hoy es el estado de
-- QuePharma. Se puede pedir igual. Ver la nota grande de la cabecera.
ALTER TABLE pedidos.pedido
    ALTER COLUMN proveedor_id DROP NOT NULL;

-- --------------------------------------------------------------------------
-- 3) Las restricciones de `pedidos.pedido`
-- --------------------------------------------------------------------------

-- La cadena vacía no existe en ninguna columna de texto de este esquema: se
-- compara igual que un dato y empareja con cualquier otra vacía.
ALTER TABLE pedidos.pedido
    DROP CONSTRAINT IF EXISTS ck_pedido_proveedor;
ALTER TABLE pedidos.pedido
    ADD CONSTRAINT ck_pedido_proveedor
        CHECK (proveedor <> '');

-- UN CERO ES UN ID INVENTADO. Cabe en un `bigint` sin protestar y a partir de
-- ahí todo `join` contra `dim_proveedor` sale vacío sin error. NULL sí es un
-- dato: dice que SICAR no lo conoce.
ALTER TABLE pedidos.pedido
    DROP CONSTRAINT IF EXISTS ck_pedido_proveedor_id;
ALTER TABLE pedidos.pedido
    ADD CONSTRAINT ck_pedido_proveedor_id
        CHECK (proveedor_id > 0);

-- UN SOLO ESTADO, y es una decisión: el de "enviado" lo estrena el ticket 21 y
-- cómo se llame es su decisión, porque `CONTEXT.md` no lo tiene todavía y el
-- glosario manda sobre el nombre de cualquier cosa. El precio, dicho: el
-- ticket 21 paga una migración para ampliar este CHECK.
ALTER TABLE pedidos.pedido
    DROP CONSTRAINT IF EXISTS ck_pedido_estado;
ALTER TABLE pedidos.pedido
    ADD CONSTRAINT ck_pedido_estado
        CHECK (estado IN ('borrador'));

-- "UNO POR PROVEEDOR DENTRO DE LA MISMA LISTA", ahora sobre la clave de Doyle.
-- El porqué está en la cabecera: con `proveedor_id` nullable, un UNIQUE sobre
-- él deja pasar dos pedidos a QuePharma porque dos nulos no son iguales.
ALTER TABLE pedidos.pedido
    DROP CONSTRAINT IF EXISTS ux_pedido_proveedor;
ALTER TABLE pedidos.pedido
    ADD CONSTRAINT ux_pedido_proveedor
        UNIQUE (pedido_sugerido_id, proveedor);

-- El destino de la llave foránea apretada del paso 5. Se crea ANTES que ella:
-- una llave foránea necesita una restricción única que la sostenga.
ALTER TABLE pedidos.pedido
    DROP CONSTRAINT IF EXISTS ux_pedido_de_la_lista;
ALTER TABLE pedidos.pedido
    ADD CONSTRAINT ux_pedido_de_la_lista
        UNIQUE (pedido_id, pedido_sugerido_id, negocio);

-- --------------------------------------------------------------------------
-- 4) `pedidos.renglon` gana la elección de proveedor, firmada
-- --------------------------------------------------------------------------
--
-- Las tres son NULLables y sin DEFAULT. NULL aquí significa "nadie eligió a
-- quién pedírselo", que es la inmensa mayoría de los renglones, y un DEFAULT
-- inventaría una decisión que nadie tomó.
--
-- **No hay columna para lo que el sistema sugiere**, y no es un olvido: la
-- sugerencia se recalcula de `comparacion.elegir_ganador`, que es pura sobre
-- una tabla de precios que solo crece (ADR 0004). Guardarla sería una segunda
-- copia del mismo hecho, y una que envejece sin avisar en cuanto llega un
-- precio nuevo. Se aparta a propósito del ticket 11, que sí guarda las dos
-- cantidades: aquella propuesta NO se puede recalcular.
ALTER TABLE pedidos.renglon
    ADD COLUMN IF NOT EXISTS proveedor_elegido text;

ALTER TABLE pedidos.renglon
    ADD COLUMN IF NOT EXISTS elegido_por text;

ALTER TABLE pedidos.renglon
    ADD COLUMN IF NOT EXISTS elegido_en timestamptz;

ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_proveedor_elegido;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_proveedor_elegido
        CHECK (proveedor_elegido <> '');

ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_elegido_por;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_elegido_por
        CHECK (elegido_por <> '');

-- Proveedor elegido si y solo si hay firma Y hora, el mismo par que
-- `ck_renglon_descarte` y `ck_renglon_ajuste`. Sin la mitad de ida, la
-- pregunta "¿por qué le compraste a LEVIC habiendo NADRO más barato?" no
-- tendría a quién hacérsele; sin la de vuelta, una firma colgada diría que
-- alguien eligió lo que nadie eligió.
ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_eleccion;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_eleccion
        CHECK ((proveedor_elegido IS NOT NULL)
               = (elegido_por IS NOT NULL AND elegido_en IS NOT NULL));

-- --------------------------------------------------------------------------
-- 5) `fk_renglon_pedido` pasa a exigir que el pedido sea de ESTA lista
-- --------------------------------------------------------------------------
--
-- Ver la cabecera. Con `(pedido_id, negocio)` un renglón del martes podía
-- colgar de un pedido del lunes sin violar nada.
ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS fk_renglon_pedido;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT fk_renglon_pedido
        FOREIGN KEY (pedido_id, pedido_sugerido_id, negocio)
        REFERENCES pedidos.pedido (pedido_id, pedido_sugerido_id, negocio);

-- --------------------------------------------------------------------------
-- Los comentarios de las columnas nuevas
-- --------------------------------------------------------------------------

COMMENT ON COLUMN pedidos.pedido.proveedor IS
    'La clave de Doyle: nadro, levic, vicma, quepharma. Es la IDENTIDAD del '
    'pedido -- a quién se le preguntó el precio y a quién se le pide--, la '
    'misma que precio_de_proveedor.proveedor.';

COMMENT ON COLUMN pedidos.pedido.proveedor_id IS
    'marts.dim_proveedor.proveedor_id (pro_id de SICAR). NULL = SICAR no lo '
    'conoce, y se le puede pedir igual; NUNCA cero. Sin FK a propósito: dbt '
    'recrea marts en cada corrida y se llevaría la restricción por delante.';

COMMENT ON COLUMN pedidos.pedido.estado IS
    'borrador. Nace así y se puede modificar mientras esté así. El estado de '
    '"enviado" lo estrena el ticket 21, con su migración del CHECK.';

COMMENT ON COLUMN pedidos.renglon.proveedor_elegido IS
    'A quién decidió una PERSONA pedírselo, con la clave de Doyle. NULL = '
    'nadie eligió; lo que el sistema sugiere no se guarda, se recalcula.';

COMMENT ON COLUMN pedidos.renglon.elegido_por IS
    'Quién eligió el proveedor, según Cf-Access-Authenticated-User-Email. Es '
    'una FIRMA, no un permiso. NULL si nadie eligió.';

COMMENT ON COLUMN pedidos.renglon.elegido_en IS
    'Cuándo se eligió, instante con zona. NULL si nadie eligió.';

COMMIT;


-- --------------------------------------------------------------------------
-- Qué quedó
-- --------------------------------------------------------------------------
--
-- Se imprime en vez de darse por hecho, igual que en las cuatro anteriores: un
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

SELECT a.attname                            AS columna,
       format_type(a.atttypid, a.atttypmod) AS tipo,
       NOT a.attnotnull                     AS admite_nulos
  FROM pg_attribute a
 WHERE a.attrelid = to_regclass('pedidos.renglon')
   AND a.attname IN ('pedido_id', 'proveedor_elegido', 'elegido_por',
                     'elegido_en')
 ORDER BY a.attname;

SELECT con.conname                   AS restriccion,
       pg_get_constraintdef(con.oid) AS definicion
  FROM pg_constraint con
 WHERE con.conrelid = to_regclass('pedidos.renglon')
   AND con.conname IN ('ck_renglon_proveedor_elegido', 'ck_renglon_elegido_por',
                       'ck_renglon_eleccion', 'fk_renglon_pedido')
 ORDER BY con.conname;

\echo ''
\echo '>> COMPRUEBA TRES COSAS ARRIBA, y las tres se pueden ver mal sin que nada falle:'
\echo '>>   1. pedido.proveedor existe y es NOT NULL; pedido.proveedor_id ADMITE NULOS.'
\echo '>>      Si proveedor_id sigue NOT NULL, a QuePharma no se le va a poder pedir.'
\echo '>>   2. ux_pedido_proveedor es UNIQUE (pedido_sugerido_id, proveedor) y NO'
\echo '>>      sobre proveedor_id. Sobre proveedor_id con nulos NO impide nada: dos'
\echo '>>      nulos no son iguales, asi que dos pedidos a QuePharma entrarian los dos.'
\echo '>>   3. fk_renglon_pedido lleva las TRES columnas (pedido_id,'
\echo '>>      pedido_sugerido_id, negocio). Con dos, un renglon del martes puede'
\echo '>>      colgar de un pedido del lunes y el total de ese pedido miente.'
\echo ''
\echo '>> sql/crear_rol.sql NO hace falta volver a correrlo: esta migracion no crea'
\echo '>> ninguna tabla y el GRANT es sobre la tabla entera. Corre SI'
\echo '>> sql/verificar_rol.sql: sus comprobaciones 23 a 26 son nuevas.'
