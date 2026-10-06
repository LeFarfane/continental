-- 0019 - el renglón se puede pasar al día siguiente (ADR 0025, 2026-10-05).
--
-- NO CREA NINGUNA TABLA: el esquema `pedidos` sigue teniendo SIETE. Lo que hace
-- es darle a `pedidos.renglon` un séptimo estado, tres columnas y tres CHECK:
--
--   - el estado `pospuesto` en `ck_renglon_estado`: una persona mandó el
--     renglón a la SIGUIENTE LISTA. Sí se necesita, pero mañana --lo típico, un
--     tope de dinero que el dueño le puso al pedido de hoy--. Sale de la lista
--     de trabajo, del total y del reparto, igual que un descartado, pero dice
--     lo contrario: "se pide mañana" y no "no se pide";
--   - `pospuesto_por` y `pospuesto_en`: la FIRMA --quién y cuándo--, con su
--     CHECK pareado `ck_renglon_pospuesto` (pospuesto si y solo si hay firma Y
--     hora), el mismo par que `ck_renglon_descarte`;
--   - `piezas_pospuestas`: las piezas que la lista anterior pasó a ESTE
--     renglón, ya sumadas a su `cantidad_propuesta`. Es el par exacto de
--     `piezas_que_faltaron` (0011): se guarda aparte para que "se vendieron 2 y
--     pasaron 3, se piden 5" se pueda verificar de un vistazo. Casi siempre 0.
--
-- ## Para qué
--
-- El ADR 0020 decidió que lo que queda sin pedir NO pasa a la lista de mañana:
-- la de ayer se cierra sola. Con un tope de dinero, la encargada solo tenía dos
-- salidas y las dos mentían: descartar (dice "no se pide") o dejarlo abierto
-- (se da por atendido al cerrar). Desde aquí un renglón se puede pasar al día
-- siguiente a propósito, uno por uno, y sus piezas se SUMAN en la siguiente
-- lista que se arme.
--
-- **No se rellena nada.** Ningún renglón anterior es `pospuesto`, y
-- `piezas_pospuestas` nace en 0, que es "no trae nada de ayer".
--
--
-- SE CORRE A MANO, UNA VEZ, CON CREDENCIALES DE DUEÑO, igual que
-- `sql/crear_tablas.sql` y las migraciones 0001 a 0018, y por la misma razón
-- (ADR 0003): esto es DDL, y el rol `continental` no puede hacer DDL a
-- propósito. **No lo corre el servicio, no lo corre una prueba y no lo corre el
-- lote de la noche.**
--
-- Desde `~/proyectos/Continental` en atlas -- **plano, no anidado**--:
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 \
--       < sql/migraciones/0019-el-renglon-pospuesto.sql
--
-- `<` y no `-f`: con `docker exec`, el `-f` de psql busca el archivo DENTRO del
-- contenedor, donde este repo no está montado. `ON_ERROR_STOP=1` porque sin él
-- psql sigue tras un error y termina diciendo que todo salió bien.
--
--
-- ## HAY QUE CORRERLA ANTES DE DESPLEGAR EL CÓDIGO DEL ADR 0025
--
-- No es opcional: `_LEER_RENGLONES` y `_LEER_RENGLON_POR_ID` NOMBRAN las
-- columnas nuevas y `_INSERTAR_RENGLONES` escribe `piezas_pospuestas`, así que
-- con el código nuevo y la base vieja **la lista del día no se puede leer ni
-- armar** -- "column pospuesto_por does not exist"-- y el lote de la noche se
-- corta. Es lo mismo que pasó con la 0005 a la 0011. `verificar --forma`
-- detiene el despliegue (paso 4 de `desplegar.sh`, ADR 0017) y nombra este
-- archivo: las tres columnas nuevas son las testigo.
--
--
-- ## `sql/crear_rol.sql` NO hace falta volver a correrlo
--
-- Aquí solo se agregan columnas y se cambian CHECK, y el `GRANT SELECT, INSERT,
-- UPDATE` es sobre la tabla entera -- no se usan permisos por columna, a
-- propósito--. Posponer y devolver son `UPDATE`, que el rol ya tiene sobre
-- `renglon` desde el ticket 07, y el `INSERT` de la lista nueva ya lo tenía.
-- De `marts` no se lee nada nuevo (regla 6 de `CLAUDE.md`).
--
--
-- ## Por qué se reemplaza `ck_renglon_estado` y no se agrega otro
--
-- Un CHECK nuevo al lado del viejo no amplía nada: los dos se tendrían que
-- cumplir y el viejo seguiría rechazando 'pospuesto'. Se tira y se vuelve a
-- crear con el MISMO nombre, que es el que citan los mensajes de
-- `almacenamiento.py` y las comprobaciones de `verificar_rol.sql`, con
-- `pospuesto` AL FINAL --el orden de la tupla `ESTADOS_DEL_RENGLON` es el del
-- CHECK, y `test_sql_del_pedido.py` los compara como tuplas--. El acento de
-- 'en tránsito' viaja dentro del CHECK: de ahí el `client_encoding` de abajo.
--
-- ## Es idempotente
--
-- Correrla dos veces no rompe nada y no cambia nada la segunda vez, igual que
-- las anteriores: `ADD COLUMN IF NOT EXISTS` y `DROP CONSTRAINT IF EXISTS`
-- antes de cada `ADD CONSTRAINT`, todo en una transacción.

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
-- 1) La firma de pasar al día siguiente
-- --------------------------------------------------------------------------
ALTER TABLE pedidos.renglon
    ADD COLUMN IF NOT EXISTS pospuesto_por text;
ALTER TABLE pedidos.renglon
    ADD COLUMN IF NOT EXISTS pospuesto_en timestamptz;

-- Las piezas que este renglón trae de la lista anterior: se SUMAN a lo vendido
-- para dar la propuesta, así que caben en ella y nunca son negativas.
ALTER TABLE pedidos.renglon
    ADD COLUMN IF NOT EXISTS piezas_pospuestas integer NOT NULL DEFAULT 0;

-- --------------------------------------------------------------------------
-- 2) El séptimo estado
-- --------------------------------------------------------------------------
ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_estado;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_estado
        CHECK (estado IN ('abierto', 'en tránsito', 'recibido',
                          'recibido parcial', 'descartado', 'cancelado',
                          'pospuesto'));

-- --------------------------------------------------------------------------
-- 3) Los CHECK
-- --------------------------------------------------------------------------

-- La firma vacía no existe, igual que en el descarte.
ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_pospuesto_por;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_pospuesto_por
        CHECK (pospuesto_por <> '');

-- POSPUESTO SI Y SOLO SI HAY FIRMA Y HORA. Sin la mitad de ida, un renglón
-- podría quedar pospuesto sin decir quién ni cuándo, y "¿por qué esto pasó a
-- mañana?" no tendría a quién hacérsele. Sin la de vuelta, un renglón devuelto
-- a `abierto` conservaría una firma que ya no describe nada.
ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_pospuesto;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_pospuesto
        CHECK ((estado = 'pospuesto')
               = (pospuesto_por IS NOT NULL AND pospuesto_en IS NOT NULL));

ALTER TABLE pedidos.renglon
    DROP CONSTRAINT IF EXISTS ck_renglon_piezas_pospuestas;
ALTER TABLE pedidos.renglon
    ADD CONSTRAINT ck_renglon_piezas_pospuestas
        CHECK (piezas_pospuestas >= 0
               AND piezas_pospuestas <= cantidad_propuesta);

-- --------------------------------------------------------------------------
-- Los comentarios
-- --------------------------------------------------------------------------

COMMENT ON COLUMN pedidos.renglon.pospuesto_por IS
    'Quién pasó este renglón al día siguiente (ADR 0025). Es una FIRMA, no un '
    'permiso. NULL si no está pospuesto.';

COMMENT ON COLUMN pedidos.renglon.pospuesto_en IS
    'Cuándo lo pasó, instante con zona. NULL si no está pospuesto.';

COMMENT ON COLUMN pedidos.renglon.piezas_pospuestas IS
    'Piezas que la lista anterior pasó al día siguiente y que este renglón trae, '
    'ya sumadas a cantidad_propuesta. Son piezas, no ventas (ADR 0025). Casi '
    'siempre 0.';

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
 WHERE con.conname IN ('ck_renglon_estado',
                       'ck_renglon_pospuesto_por',
                       'ck_renglon_pospuesto',
                       'ck_renglon_piezas_pospuestas')
 ORDER BY con.conname;

SELECT estado, count(*) AS renglones
  FROM pedidos.renglon
 GROUP BY estado
 ORDER BY estado;

\echo ''
\echo '>> COMPRUEBA ARRIBA: las cuatro restricciones, y que ck_renglon_estado'
\echo '>> traiga los siete estados con en transito CON ACENTO. Sin esta'
\echo '>> migracion, la lista del dia no se puede leer con el codigo del ADR 0025.'
\echo ''
\echo '>> sql/crear_rol.sql NO hace falta volver a correrlo: esta migracion no crea'
\echo '>> ninguna tabla y el permiso es sobre la tabla entera.'
