-- Rol acotado para Continental: solo lo que necesita, nada más.
--
-- Correr con credenciales de dueño (el usuario `farmacia` del docker-compose
-- de farmacia-data), DESPUÉS de `sql/crear_tablas.sql`. El orden importa: no
-- se puede otorgar un permiso sobre una tabla que todavía no existe.
--
-- **Y por eso también se corre después de toda migración que CREE una tabla.**
-- Es el caso de `sql/migraciones/0003-*` (ticket 12), que estrena
-- `pedidos.precio_de_proveedor`: el GRANT que este archivo corrió en su día no
-- la alcanza, porque no existía. Las migraciones que solo agregan columnas no
-- lo exigen -- el GRANT es sobre la tabla entera-- y es justo esa diferencia
-- la que hace fácil olvidarlo. Sin este paso, el primer precio que se intente
-- guardar en atlas rebota con "permission denied for table
-- precio_de_proveedor", después de que en la torre todo se vio verde.
--
-- Desde `~/proyectos/Continental` en atlas:
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 -v password="'TU_CONTRASEÑA_AQUI'" \
--       < sql/crear_rol.sql
--
-- La contraseña va entre comillas simples DENTRO de las dobles: psql sustituye
-- `:password` tal cual, sin citarlo él. Y esa misma contraseña es la que va en
-- `WAREHOUSE_URL` del `.env` de Continental (ver `.env.example`).
--
-- `<` y no `-f`: con `docker exec`, el `-f` de psql busca el archivo DENTRO
-- del contenedor, donde este repo no está montado.
--
-- "El permiso es la garantía, no la buena intención del código" -- el mismo
-- principio que el usuario `lector` de MySQL en farmacia-data y que el rol
-- `marlowe` en el repo hermano. La regla 6 de CLAUDE.md es el cinturón; esto
-- es el tirante.
--
--
-- ## Este archivo se vuelve a correr, y por eso es idempotente
--
-- No es una corrida única como el DDL. **Cada `dbt build` borra los GRANT
-- sobre los modelos de `marts`** (ver la nota grande del final), así que
-- reaplicar permisos es una operación de mantenimiento. Los GRANT son
-- idempotentes por naturaleza y la creación del rol está detrás de un `\if`:
-- si el rol ya existe **no se le toca la contraseña**, porque cambiarla en
-- silencio dejaría al servicio sin poder conectarse hasta que alguien
-- editara el `.env`.
--
--
-- ## Qué NO se otorga, y por qué
--
-- - **CREATE sobre ningún esquema.** Crear tablas es DDL y vive en
--   `sql/crear_tablas.sql`, corrido a mano por el dueño. Ni siquiera sobre
--   `pedidos`: el rol escribe FILAS en sus tablas, no crea tablas. Esto es la
--   mitad del trabajo; la otra mitad es que el esquema `pedidos` lo posee
--   `farmacia` y no `continental` -- el dueño de un esquema tiene CREATE sobre
--   él implícitamente, así que un rol propietario podría crear tablas sin que
--   ningún GRANT lo dijera.
--
-- - **DELETE y TRUNCATE, ni sobre sus propias tablas.** Continental nunca
--   borra una fila: descartar un renglón, cerrar una lista o cancelar un
--   pedido son CAMBIOS DE ESTADO, no borrados (ver los `estado` de
--   `CONTEXT.md`), y el pedido sugerido del día se lee si ya existe en vez de
--   recalcularse (ticket 08). Un permiso que el código nunca ejercita es
--   superficie de ataque gratuita -- es la misma lección que llevó a omitir
--   UPDATE en `Marlowe/sql/crear_rol.sql`. Si algún día hace falta, se agrega
--   aquí con la razón escrita, no de a poquito.
--
-- - **UPDATE sí se otorga, y ahí Continental se aparta de Marlowe a
--   propósito.** Marlowe lo omite porque escribe siempre por DELETE +
--   INSERT. Aquí es al revés: la vida de un renglón ES una sucesión de
--   UPDATEs (`abierto` -> `en tránsito` -> `recibido`), y la de una lista
--   también (`abierto` -> `cerrado` -> `vencido`). La lección heredada no es
--   "omite UPDATE", es "otorga exactamente lo que el código ejercita".
--
-- - **Nada de `raw`, `curado` ni `staging`, y de `marts` solo cinco tablas.**
--   Ese es justo el punto de tener un rol aparte en vez de reusar `farmacia`.
--   `fct_merma`, `fct_caducidad` y `fct_precio_competencia` viven en `marts` y
--   Continental no las lee: no aparecen aquí.
--
-- - **`ALTER DEFAULT PRIVILEGES` sobre `marts`, que sería la tentación
--   evidente** para que los GRANT sobrevivan a `dbt build`. No se usa porque
--   otorgaría SELECT sobre TODO modelo nuevo que dbt cree en `marts`, incluidos
--   los que Continental no debe leer. Arregla el síntoma rompiendo el
--   principio. La solución correcta vive del lado de farmacia-data: ver el
--   final de este archivo.
--
-- Cuando termine, corre `sql/verificar_rol.sql`: dice caso por caso si esto
-- quedó como aquí se describe, y truena si no.

SET client_encoding TO 'UTF8';

SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'continental') AS ya_existe
\gset

\if :ya_existe
\echo '>> El rol continental ya existia: NO se le toca la contrasena.'
\echo '>> Se reaplican los permisos (que es lo que hace falta tras un dbt build).'
\else
CREATE ROLE continental WITH LOGIN PASSWORD :password;
\endif

-- Sin atributos de administrador, explícito aunque sean los valores por
-- omisión: escribirlo hace que una lectura del archivo baste para saberlo, y
-- deshace de paso cualquier atributo que alguien le haya puesto a mano.
ALTER ROLE continental
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;


-- --------------------------------------------------------------------------
-- Lo suyo: las tres tablas del pedido
-- --------------------------------------------------------------------------

-- USAGE sobre el esquema y NADA MÁS. Sin esto el rol ni siquiera puede ver que
-- las tablas existen, aunque tenga SELECT sobre ellas. Con CREATE además
-- podría crear las suyas, que es lo que no debe.
GRANT USAGE ON SCHEMA pedidos TO continental;

-- Defensivo: si alguien otorgó CREATE alguna vez, aquí se deshace. Un REVOKE
-- de algo que no se tiene no falla.
REVOKE CREATE ON SCHEMA pedidos FROM continental;

-- Y el esquema `public`, que es el que se olvida. Hasta PostgreSQL 14, PUBLIC
-- traía CREATE sobre `public` por omisión, así que **todo rol podía crear
-- tablas ahí** sin que ningún GRANT lo dijera: la garantía de este archivo
-- dependía de la versión del servidor y no de lo que aquí está escrito.
-- PostgreSQL 15 quitó ese permiso, y farmacia-data corre `postgres:16`
-- (docker-compose.yml, revisado el 2026-09-19), así que hoy el hueco no está
-- abierto. Se revoca igual: cuesta una línea y hace que la afirmación "el rol
-- no puede crear tablas" deje de depender de qué imagen se levante mañana.
-- El caso 8 de `verificar_rol.sql` pregunta por TODOS los esquemas, así que es
-- quien lo cazaría si alguna vez volviera.
--
-- Se revoca del rol y **no de PUBLIC**, aunque en un servidor anterior a la 15
-- solo el segundo cerraría el hueco: un permiso que llega por PUBLIC no se
-- quita revocándoselo a un rol. `REVOKE CREATE ON SCHEMA public FROM PUBLIC`
-- se lo quitaría a TODOS —dbt y Metabase incluidos—, y eso es una decisión de
-- farmacia-data y no de este repo. Es el mismo criterio con el que el permiso
-- de tablas temporales quedó documentado en vez de arreglado a ciegas. Si
-- alguna vez esto corre sobre un Postgres anterior a la 15, `verificar_rol.sql`
-- lo va a decir y ahí se decide allá.
REVOKE CREATE ON SCHEMA public FROM continental;

GRANT SELECT, INSERT, UPDATE ON pedidos.pedido_sugerido      TO continental;
GRANT SELECT, INSERT, UPDATE ON pedidos.renglon              TO continental;
GRANT SELECT, INSERT, UPDATE ON pedidos.pedido               TO continental;

-- La cuarta, desde el ticket 12: el precio congelado por renglón y proveedor.
--
-- **Se otorga UPDATE aunque hoy ningún código lo ejercite**, y ésa es la
-- excepción a "otorga exactamente lo que el código ejercita" -- así que va con
-- su razón escrita, que es la condición que ese principio pone. Las otras tres
-- tablas usan UPDATE para sus cambios de estado; ésta SOLO CRECE a propósito
-- (ver `crear_tablas.sql`), así que en rigor le bastaría SELECT e INSERT.
--
-- Se otorga igual porque la alternativa es peor de las dos maneras: con un
-- GRANT distinto por tabla, la comprobación 6 de `verificar_rol.sql` deja de
-- poder ser "no le falta ninguno sobre ninguna" y pasa a ser una lista de
-- parejas tabla-permiso que hay que mantener a mano -- justo el tipo de lista
-- que se queda vieja y da luz verde sobre un rol que quedó mal. Y el riesgo
-- que se evitaría es corto: un UPDATE sobre esta tabla no puede borrar una
-- fila ni pisar un precio sin que alguien escriba la sentencia a propósito, y
-- quien puede hacer eso ya tiene la contraseña del `.env`.
--
-- Si algún día vale la pena apretarlo, el lugar es aquí y la comprobación que
-- hay que reescribir es la 6. No al revés.
GRANT SELECT, INSERT, UPDATE ON pedidos.precio_de_proveedor TO continental;

-- Sin GRANT sobre secuencias, y no es un olvido: las tres llaves son
-- `GENERATED ALWAYS AS IDENTITY`, y la secuencia de una columna de identidad
-- es interna a la tabla -- el INSERT sobre la tabla basta. Con `serial` haría
-- falta además `USAGE` sobre la secuencia, un permiso extra fácil de olvidar
-- que se manifiesta como "permission denied for sequence" en el primer INSERT
-- de producción. La comprobación 16 de `verificar_rol.sql` confirma que las
-- tres siguen siendo de identidad.


-- --------------------------------------------------------------------------
-- Lo ajeno: solo lectura sobre `marts`, y solo lo que lee el código
-- --------------------------------------------------------------------------
--
-- Las cinco salen de `src/continental/almacen.py` y del ticket 07. Cada una
-- con su consumidor concreto: si alguna deja de tenerlo, se quita de aquí.

GRANT USAGE ON SCHEMA marts TO continental;

-- `almacen.ventas()` y `almacen.ultima_fecha_con_ventas()`: lo que se repone
-- (reposición 1 a 1) y el ancla temporal que evita mirar el reloj.
GRANT SELECT ON marts.fct_ventas TO continental;

-- `almacen.catalogo()`: anaquel, existencia y el EAN, que es lo único que
-- empareja nuestro producto con el de un proveedor.
GRANT SELECT ON marts.dim_producto TO continental;

-- El `join` de las dos consultas de arriba y el de compras: `fct_ventas` y
-- `fct_compras` guardan `fecha_id`, no la fecha. Sin esta tabla las tres
-- lecturas truenan con "permission denied for table dim_fecha" -- el hueco
-- exacto que Marlowe destapó el 2026-09-05.
GRANT SELECT ON marts.dim_fecha TO continental;

-- `almacen.compras_desde()`: la evidencia con la que se propone "probablemente
-- recibido". SICAR no tiene pedidos, así que una compra que encaja es lo único
-- que hay para sugerir que un renglón en tránsito llegó.
GRANT SELECT ON marts.fct_compras TO continental;

-- El nombre del proveedor al que se le pide. `pedidos.pedido.proveedor_id`
-- guarda el id y nada más; sin esta tabla la pantalla diría "proveedor 3" en
-- vez de "NADRO".
GRANT SELECT ON marts.dim_proveedor TO continental;


-- --------------------------------------------------------------------------
-- OJO: los GRANT sobre `marts` son un respaldo, no la garantía
-- --------------------------------------------------------------------------
--
-- **Recrear una tabla en Postgres borra sus permisos**, y cada `dbt build`
-- recrea los modelos de `marts`. Un GRANT dado a mano dura hasta la siguiente
-- corrida de la cadena nocturna (lunes a viernes, 20:30), y a la mañana
-- siguiente Continental se cae con "permission denied for table fct_ventas"
-- sin que nadie haya tocado una línea de código.
--
-- No es una hipótesis: Marlowe lo midió el 2026-09-06 -- se otorgó a mano,
-- corrió el barrido, y la interfaz se cayó exactamente así.
--
-- QUÉ HAY QUE HACER DEL LADO DE farmacia-data (repo `Farmacia`, carpeta
-- `dbt/models/marts/`), y sin esto lo de arriba se borra solo:
--
--   1. Agregar `continental` al `grants` que ya tienen cuatro modelos:
--
--        dim_fecha.sql     {{ config(grants={'select': ['marlowe', 'continental']}) }}
--        dim_producto.sql  {{ config(grants={'select': ['marlowe', 'continental']}) }}
--        fct_ventas.sql    {{ config(grants={'select': ['marlowe', 'continental']}) }}
--        fct_compras.sql   {{ config(grants={'select': ['marlowe', 'continental']}) }}
--
--   2. **`dim_proveedor.sql` hoy no tiene `grants` en absoluto** (revisado el
--      2026-09-19): hay que agregarle la línea entera.
--
--        {{ config(grants={'select': ['continental']}) }}
--
--   3. Correr `cd dbt && ../.venv/bin/dbt build` una vez, y volver a correr
--      `sql/verificar_rol.sql`. La comprobación 9 compara la lista de tablas
--      de `marts` que el rol puede leer contra las cinco esperadas, así que
--      detecta tanto que falte una (dbt se la llevó) como que sobre otra
--      (alguien otorgó de más).
--
-- dbt vuelve a aplicar el `grants` en cada construcción, y **eso** es lo que
-- de verdad sostiene estos permisos. Mientras el paso 1-2 no esté hecho, dar
-- por buena una corrida verde de `verificar_rol.sql` es darla por buena hasta
-- las 20:30 de hoy.


\echo ''
\echo '>> Siguiente paso: sql/verificar_rol.sql (el veredicto, caso por caso).'
