-- 0021 - el esquema `pedidos` gana una OCTAVA tabla,
-- `pedidos.minimo_del_proveedor`: lo que cada proveedor pide como mínimo para
-- surtir un pedido (lista de espera, ticket 08; enmienda del 2026-10-05 al ADR
-- 0025, punto 7).
--
-- UNA FILA POR NEGOCIO Y PROVEEDOR, sobreescrita con su firma y SIN HISTORIAL:
-- importa el valor de hoy y quién lo puso. El `monto` es TAL COMO LO DICE EL
-- PROVEEDOR, y `incluye_iva` dice con qué base: no se convierte al guardar
-- (convertirlo obligaría a quien lo captura a restar cifras con y sin IVA, la
-- trampa que ya volteó una flecha en Marlowe).
--
--   - SIN FILA = «sin mínimo capturado»: nadie lo ha dicho.
--   - `monto = 0` = «no tiene mínimo»: alguien lo dijo.
--
-- Son dos cosas distintas y por eso la ausencia es la ausencia de la fila y no
-- un cero centinela (regla 4 de CLAUDE.md: sin dato, jamás un cero).
--
-- `fijado_por` es el correo de Access: una firma, no un permiso (regla 3).
--
--
-- SE CORRE A MANO, UNA VEZ, CON CREDENCIALES DE DUEÑO, como todas (ADR 0003):
-- esto es DDL, y el rol `continental` no puede hacer DDL a propósito. **No lo
-- corre el servicio, no lo corre una prueba y no lo corre el lote de la noche.**
--
-- Desde `~/proyectos/Continental` en atlas -- **plano, no anidado**--:
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 \
--       < sql/migraciones/0021-el-minimo-del-proveedor.sql
--
-- `<` y no `-f`: con `docker exec`, el `-f` de psql busca el archivo DENTRO del
-- contenedor. `ON_ERROR_STOP=1` porque sin él psql sigue tras un error y
-- termina diciendo que todo salió bien.
--
--
-- ## VA ANTES DE DESPLEGAR el código que la lee
--
-- La pestaña Ajustes la lee al abrirse; sin la tabla dice que no pudo leerla.
-- `verificar --forma` detiene el despliegue (paso 4 de `desplegar.sh`, ADR
-- 0017) y nombra este archivo: la tabla nueva es la columna testigo.
--
--
-- ## EL GRANT VIENE AQUÍ MISMO
--
-- Un permiso no se puede dar sobre una tabla que no existía, y volver a correr
-- `crear_rol.sql` pide la contraseña del rol. `crear_rol.sql` lleva el mismo
-- GRANT para una base desde cero. **SELECT, INSERT y UPDATE** -- como las demás
-- tablas que cambian de valor --: guardar un mínimo es `insert ... on conflict
-- do update`. Sin DELETE, como ninguna.
--
-- ## Es idempotente
--
-- Correrla dos veces no rompe nada: `CREATE TABLE IF NOT EXISTS`, el GRANT se
-- puede repetir, y los COMMENT se reescriben iguales.

\set ON_ERROR_STOP on

SET client_encoding TO 'UTF8';

-- Que no lo corra quien no debe, igual que las anteriores.
DO $guardia$
BEGIN
    IF current_user = 'continental' THEN
        RAISE EXCEPTION '%',
            'Esta migración se corre con credenciales de DUEÑO (usuario '
            || 'farmacia), no con el rol acotado continental: el rol no tiene '
            || 'CREATE sobre su esquema y eso es deliberado (ADR 0003).';
    END IF;
END
$guardia$;

BEGIN;

CREATE TABLE IF NOT EXISTS pedidos.minimo_del_proveedor (
    negocio      text          NOT NULL,
    proveedor    text          NOT NULL,
    monto        numeric(12,2) NOT NULL,
    incluye_iva  boolean       NOT NULL,
    fijado_por   text          NOT NULL,
    fijado_en    timestamptz   NOT NULL DEFAULT now(),

    CONSTRAINT pk_minimo_del_proveedor
        PRIMARY KEY (negocio, proveedor),

    CONSTRAINT ck_minimo_negocio
        CHECK (negocio <> ''),

    CONSTRAINT ck_minimo_proveedor
        CHECK (proveedor <> ''),

    CONSTRAINT ck_minimo_monto
        CHECK (monto >= 0),

    CONSTRAINT ck_minimo_fijado_por
        CHECK (btrim(fijado_por) <> '')
);

COMMENT ON TABLE pedidos.minimo_del_proveedor IS
    'Lo que cada proveedor pide como mínimo para surtir, tal como lo dice él. Una fila por negocio y proveedor, sobreescrita con su firma, sin historial. Sin fila = sin mínimo capturado; monto 0 = no tiene mínimo.';
COMMENT ON COLUMN pedidos.minimo_del_proveedor.monto IS
    'El mínimo tal como lo dice el proveedor, con la base de IVA de incluye_iva. 0 quiere decir que no tiene mínimo.';
COMMENT ON COLUMN pedidos.minimo_del_proveedor.incluye_iva IS
    'Si el monto que dijo el proveedor ya trae IVA. No se convierte al guardar: se compara contra el total del pedido en esta misma base.';
COMMENT ON COLUMN pedidos.minimo_del_proveedor.fijado_por IS
    'Correo de Cloudflare Access de quien lo puso. Es una firma, no un permiso.';

GRANT SELECT, INSERT, UPDATE ON pedidos.minimo_del_proveedor TO continental;

COMMIT;

SELECT count(*) AS columnas
  FROM information_schema.columns
 WHERE table_schema = 'pedidos' AND table_name = 'minimo_del_proveedor';

\echo ''
\echo '>> Arriba deben salir 6 columnas. Despues: sql/verificar_rol.sql.'
