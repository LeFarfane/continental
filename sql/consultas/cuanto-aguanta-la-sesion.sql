-- ¿Cuánto tiempo SIN USO aguanta viva la sesión de un proveedor?
--
-- Solo lectura. No escribe, no crea nada. Nació el 2026-09-27 para averiguar
-- por qué caduca LEVIC (ver docs/propuestas/por-que-caduca-la-sesion-de-levic.md).
--
-- La idea: cada fila de `pedidos.precio_de_proveedor` es una visita al portal
-- con su instante. Si el motivo NO es 'la sesión caducó', el portal contestó y
-- la sesión estaba viva (sin resultados, no empareja y varios resultados son
-- el portal contestando). Entre dos visitas seguidas hay un hueco sin uso; lo
-- que interesa es:
--
--   * el hueco MÁS LARGO que la sesión aguantó (viva -> viva), y
--   * el hueco que la mató (viva -> caducó).
--
-- Si la sesión muere por inactividad, todos los huecos que la mataron serán
-- más largos que todos los que aguantó, y el límite está entre los dos. Si
-- hay huecos cortos que la mataron y largos que aguantó, NO es inactividad:
-- es otra cosa (un segundo inicio de sesión, un reinicio del portal).
--
-- Ojo: solo ve las visitas que hizo Continental (lote y botón de completar).
-- Las búsquedas desde la pantalla propia de Doyle no quedan aquí, y también
-- mantienen viva la sesión; un hueco "aguantado" puede ser más corto de lo que
-- parece. Un hueco que MATÓ sí es una cota confiable solo si nadie usó Doyle
-- en medio.
--
-- Desde `~/proyectos/Continental` en atlas:
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v proveedor=levic < sql/consultas/cuanto-aguanta-la-sesion.sql
--
-- Sin `-v proveedor=...` falla a propósito en vez de adivinar.

\set ON_ERROR_STOP 1

WITH visitas AS (
    SELECT consultado_en,
           (motivo IS DISTINCT FROM 'la sesión caducó') AS viva
      FROM pedidos.precio_de_proveedor
     WHERE lower(proveedor) = lower(:'proveedor')
),
-- Varias filas en el mismo minuto son la misma racha; se colapsan para que
-- los huecos sean entre visitas de verdad y no entre renglones de un lote.
por_minuto AS (
    SELECT date_trunc('minute', consultado_en) AS minuto,
           bool_and(viva) AS viva
      FROM visitas
     GROUP BY 1
),
con_anterior AS (
    SELECT minuto,
           viva,
           lag(minuto) OVER (ORDER BY minuto) AS minuto_anterior,
           lag(viva)   OVER (ORDER BY minuto) AS anterior_viva
      FROM por_minuto
)
SELECT minuto_anterior AT TIME ZONE 'America/Mexico_City' AS desde,
       minuto          AT TIME ZONE 'America/Mexico_City' AS hasta,
       minuto - minuto_anterior                           AS hueco_sin_uso,
       CASE WHEN viva THEN 'aguantó' ELSE 'la mató' END   AS resultado
  FROM con_anterior
 WHERE anterior_viva            -- solo huecos que empezaron con la sesión viva
   AND minuto - minuto_anterior >= interval '5 minutes'
 ORDER BY hueco_sin_uso DESC
 LIMIT 40;
