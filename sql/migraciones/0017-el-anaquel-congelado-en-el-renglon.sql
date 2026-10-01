-- 0017 - el anaquel congelado en el renglón (2026-09-30).
--
-- NO CREA NINGUNA TABLA: el esquema `pedidos` sigue teniendo CINCO. Le da a
-- `pedidos.renglon` UNA columna, `anaquel`, de tipo `text`, que admite nulos,
-- sin DEFAULT y sin CHECK. Es una columna más, no una decisión de arquitectura:
-- por eso no lleva ADR (la decisión de enseñarlo está en el ADR 0023).
--
-- ## Para qué
--
-- El detalle del renglón de la pantalla enseña en qué anaquel está el producto
-- ("GENERICO 3"). El renglón guardaba `clasificacion` -que se deduce del
-- anaquel- pero no el anaquel. Se guarda JUNTO a la clasificación y no se lee
-- del catálogo al responder, por el mismo principio de todo el renglón:
-- existencia, cobertura y clasificación son "tal como venían cuando se
-- propuso", y un anaquel releído de `dim_producto` podría contradecir la
-- clasificación con que se ordenó la lista (el producto cambió de anaquel
-- ayer, y la pantalla diría "GENERICO 3" al lado de una clasificación de
-- abarrote).
--
-- Valores: NULL = "no se sabe" (toda fila anterior a esta migración; no hay de
-- dónde rellenarla sin reescribir la historia); '' = "no hay anaquel que
-- enseñar" (el catálogo no lo tiene ubicado, o el producto no está en el
-- catálogo); cualquier otro texto = el anaquel tal cual. La pantalla/JSON dice
-- `null` en el primer caso y `""` en el segundo.
--
-- ## NO ROMPE EL CÓDIGO QUE HOY CORRE EN ATLAS
--
-- Se puede correr antes de desplegar sin que el servicio de hoy lo note: su
-- `INSERT` de renglones no nombra la columna y queda en NULL, y ninguna de sus
-- lecturas la pide. Por eso es nullable y sin DEFAULT.
--
-- ## HAY QUE CORRERLA ANTES DE DESPLEGAR EL CÓDIGO NUEVO
--
-- `_LEER_RENGLONES`, `_LEER_RENGLON_POR_ID`, `_LO_YA_PEDIDO`, `_EN_TRANSITO` e
-- `_INSERTAR_RENGLONES` nombran la columna: con el código nuevo y la base
-- vieja la lista del día no se puede leer ni armar ("column anaquel does not
-- exist") y el lote de la noche se corta. `python -m continental.verificar
-- --forma` (paso 4 de `scripts/desplegar.sh`) lo detiene antes del reinicio y
-- nombra este archivo.
--
--
-- SE CORRE A MANO, UNA VEZ, CON CREDENCIALES DE DUEÑO, igual que
-- `sql/crear_tablas.sql` y las migraciones anteriores, y por la misma razón
-- (ADR 0003): esto es DDL, y el rol `continental` no puede hacer DDL a
-- propósito. **No lo corre el servicio, no lo corre una prueba y no lo corre el
-- lote de la noche.**
--
-- Desde `~/proyectos/Continental` en atlas -- **plano, no anidado**--:
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 \
--       < sql/migraciones/0017-el-anaquel-congelado-en-el-renglon.sql
--
-- `<` y no `-f`: con `docker exec`, el `-f` de psql busca el archivo DENTRO del
-- contenedor, donde este repo no está montado.
--
-- ## `sql/crear_rol.sql` NO hace falta volver a correrlo
--
-- El `GRANT SELECT, INSERT, UPDATE` es sobre la tabla entera -- no se usan
-- permisos por columna, a propósito--, así que cubre la columna nueva. Lo que
-- sí conviene correr después es `sql/verificar_rol.sql`: tiene una comprobación
-- nueva (la 40).
--
-- ## Es idempotente
--
-- `ADD COLUMN IF NOT EXISTS`, en una transacción: correrla dos veces no cambia
-- nada la segunda.

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

ALTER TABLE pedidos.renglon ADD COLUMN IF NOT EXISTS anaquel text;

COMMENT ON COLUMN pedidos.renglon.anaquel IS
    'El anaquel con que se propuso el renglón, tal como vino del catálogo y '
    'congelado junto a la clasificación. NULL = no se sabe (fila anterior a la '
    '0017); cadena vacía = no hay anaquel que enseñar.';

COMMIT;

SELECT a.attname, format_type(a.atttypid, a.atttypmod) AS tipo, a.attnotnull
  FROM pg_attribute a
 WHERE a.attrelid = to_regclass('pedidos.renglon')
   AND NOT a.attisdropped
   AND a.attname = 'anaquel';

\echo ''
\echo '>> Arriba debe salir anaquel, text, attnotnull = f.'
