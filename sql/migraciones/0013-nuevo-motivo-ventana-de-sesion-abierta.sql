-- 0013 - `precios.MOTIVOS` gana un noveno motivo: `quedó una ventana de
-- sesión abierta`.
--
-- NO CREA NINGUNA TABLA Y NO AGREGA NINGUNA COLUMNA: el esquema `pedidos`
-- sigue teniendo CINCO tablas y `precio_de_proveedor` sigue teniendo las
-- mismas columnas. Lo único que cambia es la lista de valores que
-- `ck_precio_motivo_conocido` acepta en `motivo`.
--
-- ## Para qué
--
-- Medido contra los cuatro portales reales el 2026-09-23: tres situaciones
-- distintas se estaban guardando todas como `el portal no contestó`, y solo
-- una de las tres lo era de verdad.
--
--   1. QuePharma y VICMA, mismo EAN: el portal SÍ contestó -- "No se
--      encontraron artículos"--. Se reclasifica como `sin resultados`, que ya
--      existía; no hace falta un valor nuevo para este caso.
--   2. VICMA, otro EAN: Playwright no pudo abrir el navegador porque una
--      ventana de sesión de ESE proveedor ya estaba reteniendo el perfil de
--      Chromium (`BrowserType.launch_persistent_context: ... the profile is
--      already in use`). Esto **sí** es un motivo nuevo: no es el portal, es
--      nuestro lado, y se arregla cerrando esa ventana, no reintentando la
--      búsqueda ni abriendo una sesión nueva.
--
-- La clasificación vive en `continental.precios._motivo_del_error`, sobre el
-- mensaje que ya manda Doyle -- no se tocó el repo de Doyle ni su
-- vocabulario--.
--
-- ## Es idempotente
--
-- Correrla dos veces no rompe nada y no cambia nada la segunda vez, igual que
-- las doce anteriores: `DROP CONSTRAINT IF EXISTS` antes de `ADD CONSTRAINT`,
-- todo en una transacción.
--
-- ## NO ROMPE EL CÓDIGO QUE HOY CORRE EN ATLAS
--
-- Se puede correr antes de desplegar sin que el servicio de hoy lo note: el
-- código viejo nunca escribe `quedó una ventana de sesión abierta`, así que
-- ensanchar el CHECK antes de que exista el código que lo escribe no rechaza
-- nada que antes se aceptara. Lo que SÍ rompería el orden contrario -- código
-- nuevo contra CHECK viejo--: el primer INSERT con ese motivo rebotaría con
-- "el nuevo row para la relación precio_de_proveedor viola la restricción de
-- comprobación ck_precio_motivo_conocido", DENTRO del hilo que consulta, así
-- que la pantalla solo diría "no se pudo guardar el precio" (regla 5) hasta
-- que alguien mirara el journal. Por eso esta migración se corre ANTES de
-- desplegar el código de este ticket.
--
--
-- SE CORRE A MANO, UNA VEZ, CON CREDENCIALES DE DUEÑO, igual que
-- `sql/crear_tablas.sql` y las migraciones 0001 a 0012, y por la misma razón
-- (ADR 0003): esto es DDL, y el rol `continental` no puede hacer DDL a
-- propósito. **No lo corre el servicio, no lo corre una prueba y no lo corre
-- el lote de la noche.**
--
-- Desde `~/proyectos/Continental` en atlas -- **plano, no anidado**--:
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 \
--       < sql/migraciones/0013-nuevo-motivo-ventana-de-sesion-abierta.sql
--
-- `<` y no `-f`: con `docker exec`, el `-f` de psql busca el archivo DENTRO
-- del contenedor, donde este repo no está montado. `ON_ERROR_STOP=1` porque
-- sin él psql sigue tras un error y termina diciendo que todo salió bien.
--
--
-- ## `sql/crear_rol.sql` NO hace falta volver a correrlo
--
-- Igual que la 0005 a la 0012: aquí solo se reemplaza un CHECK, y el
-- `GRANT SELECT, INSERT, UPDATE` es sobre la tabla entera. Escribir el motivo
-- nuevo es un `INSERT` como cualquier otro, que el rol ya tiene sobre
-- `precio_de_proveedor` desde el ticket 12.
--
-- Lo que SÍ conviene correr después es `sql/verificar_rol.sql`: su
-- comprobación 19 ahora espera los NUEVE motivos, no ocho.
--
-- ## Los acentos viajan dentro del CHECK
--
-- Igual que la 0003: si psql manda este archivo como latin1, el CHECK
-- guardaría 'quedÃ³ una ventana de sesiÃ³n abierta' y el primer INSERT con
-- ese motivo rebotaría con una violación de restricción que nadie sabría
-- explicar. Por eso el SET client_encoding de abajo.

SET client_encoding TO 'UTF8';

-- Que no lo corra quien no debe, igual que las doce anteriores.
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
-- `ck_precio_motivo_conocido` gana `quedó una ventana de sesión abierta`
-- --------------------------------------------------------------------------
ALTER TABLE pedidos.precio_de_proveedor
    DROP CONSTRAINT IF EXISTS ck_precio_motivo_conocido;
ALTER TABLE pedidos.precio_de_proveedor
    ADD CONSTRAINT ck_precio_motivo_conocido
        CHECK (motivo IS NULL OR motivo IN (
            'sin resultados', 'varios resultados', 'no empareja',
            'el portal no contestó', 'la sesión caducó',
            'quedó una ventana de sesión abierta',
            'no se sabe leer la página', 'no alcanzó el tiempo',
            'precio ilegible'));

COMMIT;


-- --------------------------------------------------------------------------
-- Qué quedó
-- --------------------------------------------------------------------------
--
-- Se imprime en vez de darse por hecho, igual que en las doce anteriores.

SELECT con.conname                    AS restriccion,
       pg_get_constraintdef(con.oid)  AS definicion
  FROM pg_constraint con
 WHERE con.conrelid = to_regclass('pedidos.precio_de_proveedor')
   AND con.conname = 'ck_precio_motivo_conocido';

\echo ''
\echo '>> COMPRUEBA ARRIBA: el CHECK trae los NUEVE motivos, con sus acentos y'
\echo '>> con "quedo una ventana de sesion abierta" entre ellos.'
\echo '>> sql/crear_rol.sql NO hace falta volver a correrlo: esta migracion no crea'
\echo '>> ninguna tabla ni columna. Corre SI sql/verificar_rol.sql: su'
\echo '>> comprobacion 19 ahora espera nueve.'
