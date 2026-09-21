# 0017 — El despliegue mira la forma de la base antes de reiniciar, y el lote también

**Fecha:** 2026-09-21  ·  **Estado:** aceptada (por el dueño, 2026-09-21)

El material completo —el hueco eslabón por eslabón, las siete alternativas con
lo que cada una detecta y lo que no, y la tabla que las compara— está en
`docs/propuestas/verificar-la-forma-de-la-base.md`. Este ADR registra lo que se
eligió, lo que se descartó y lo que quedó construido.

## Contexto

Las migraciones `0006` a `0012` agregan columnas, y el código nuevo las nombra
en sus sentencias (`_LEER_RENGLONES`, `_LEER_PEDIDOS`, `_REABRIR`…). Con la
base sin migrar, la lista del día rebota con `column ... does not exist` y el
lote de las 22:00 se corta igual. Ningún paso de `scripts/desplegar.sh` lo veía:
`pytest` corre sin Postgres, `/api/salud` no toca la base, y
`continental.verificar` —que ya leía la forma de `pedidos.pedido`— corría
**después** del reinicio y, además, reportaba la falta de `enviado_por` como
`PENDIENTE` con salida cero. Lo único que miraba las columnas era
`sql/verificar_rol.sql`, a mano y con credenciales de dueño.

## Decisión

**C + D, con la variante del lote de E y la prueba G. F queda para después.**

- **C — la forma, leída como el rol.** `src/continental/forma.py` compara las
  columnas reales de cada tabla de `pedidos` (`select * from pedidos.<t> limit
  0`, lo que el rol ya puede hacer) contra las que declara
  `sql/crear_tablas.sql`. Una columna que falta se cruza con los `ADD COLUMN` y
  los `CREATE TABLE` de `sql/migraciones/` y el mensaje nombra **el archivo
  exacto**, con el comando de siempre
  (`docker exec -i farmacia_warehouse psql -U farmacia -d farmacia -v ON_ERROR_STOP=1 < sql/migraciones/NNNN-....sql`),
  cada migración una vez y en orden. Si una crea una tabla, después va
  `crear_rol.sql`. Se corre con `python -m continental.verificar --forma`, y la
  corrida completa de `verificar` la incluye también.
- **Columnas de más: `PENDIENTE`, no falla.** La base va adelante del código
  —se migró y todavía no se despliega—, que es el orden correcto; el código de
  hoy no las nombra, así que no le estorban. Se dicen para que una columna
  agregada a mano no pase sin que nadie pregunte.
- **D — dónde corre.** Paso `4/7` de `desplegar.sh`, después de las pruebas y
  **antes** del `systemctl restart`, y detiene el despliegue si falla. Los
  invariantes sobre los **datos** se quedan al final (`7/7`), sin bloquear
  nada: un dato roto no tiene por qué impedir que un código bueno llegue, pero
  un código que nombra columnas que la base no tiene no es bueno para esa base.
- **E, sólo el lote.** `python -m continental.lote` llama a
  `forma.antes_del_lote()` antes de construir nada. Si la forma no cuadra —o no
  se pudo averiguar— no corre: el informe va al journal con el comando que lo
  arregla, el latido a Kuma va `down` con las migraciones que faltan, y sale
  con 1. No escribe la fila de `corrida_del_lote` (el lote no corrió, y esa
  tabla puede ser justo la que falta). Si cuadra, no late: el latido de una
  noche buena lo sigue mandando la corrida al final. Es lo que tapa la trampa
  de D: el `git pull` del paso 1 ya dejó el código nuevo en disco aunque el
  despliegue se haya detenido, y el timer lo usaría.
- **G — coherencia de los archivos, en el suite.** `tests/test_forma.py` saca
  las columnas que nombran las 41 sentencias `text(...)` de
  `almacenamiento.py` (ya armadas, incluidas las f-strings) y exige que estén en
  `crear_tablas.sql`; y exige que toda columna que agrega una migración esté
  también ahí (la regla de "dos archivos" del ADR 0003, ahora comprobada).
  Hoy el código nombra las 87 columnas del DDL.
- **El invariante 3 deja de callar.** `revisar_pedidos_enviados` sin `estado` o
  `enviado_por` pasa de `PENDIENTE` a `FALLA`: desde el ticket 21 el código las
  nombra, así que faltar es una migración sin correr. Su reparación manda a
  `--forma`, que da el archivo exacto. Las dos fallan juntas y dicen lo mismo.

## Opciones descartadas

- **A. Tabla `pedidos.migracion` con el número de cada una.** Guarda una
  afirmación, no el hecho: un `DROP COLUMN` a mano o una fila escrita sin
  correr la migración dan verde. Además es una sexta tabla sin `negocio`
  (regla 7), pide GRANT y trabajo en cada migración futura, y para rellenar las
  once que ya existen con honestidad hay que leer la forma de todos modos.
- **B. `COMMENT ON SCHEMA` con la versión.** Lo mismo que A, sin historia, y
  sobre un texto libre que hoy es lo único que dice de quién es el esquema.
  Rellenar las existentes sería a mano y por fe.
- **E aplicada al servicio web.** Convertiría la falla de una pantalla en la
  caída de la puerta entera (502 en todo `farmacia.farfanlab.uk`), llega
  después del reinicio —cuando el código viejo que funcionaba ya se perdió— y
  mezcla "no pude preguntar" con "no cuadra" en el arranque tras un corte de
  luz. **El servicio web no se niega a arrancar por la forma**; hay una prueba
  que lo cuida.
- **F. `EXPLAIN` de cada sentencia del código.** Es la más completa (ve también
  `marts` y las restricciones nombradas), pero su parte frágil —los parámetros
  de relleno y la clasificación por SQLSTATE— sólo se puede medir en atlas.
  Entra después, sobre C ya en verde.

## Lo que esto NO ve

Tipos, nulabilidad y CHECK (siguen en `sql/verificar_rol.sql`; lo que traen
las migraciones viaja con su columna en la misma transacción); una columna que
el código nombra y el DDL no declara (la ve G, en la torre); nada fuera de
`pedidos`.

## ADR 0003 intacto

Nada de esto crea, altera ni borra. `forma.py` ejecuta una sola sentencia,
`select * from pedidos.<t> limit 0`, y hay pruebas que lo exigen. Lee los
archivos de `sql/migraciones/` como **texto**, para nombrar la que falta; no
los ejecuta. Por eso las dos pruebas que prohibían la palabra `migraciones` en
`src/` (`test_ajuste.py`, `test_descarte.py`) ahora exceptúan `forma.py` y, a
cambio, exigen ahí que lo único ejecutado sea ese `select`.

## Consecuencias

- El primer despliegue con esto sobre una base atrasada **se detendrá en el
  paso 4** y nombrará las migraciones pendientes. Es lo que se quiere. El orden
  para el dueño es el de la propuesta: correr las migraciones con credenciales
  de dueño, luego `verificar_rol.sql`, luego `desplegar.sh`.
- Cada migración futura no cuesta nada extra: su `ADD COLUMN` y la línea en
  `crear_tablas.sql` —lo que ya se exigía— son todo lo que el chequeo necesita.
- Una migración que sólo cambie un CHECK o un dato, sin agregar columna ni
  tabla, no deja testigo y esto no la ve. Si llega una así, o se le da una
  columna testigo o se reabre este ADR hacia F.
- Una columna que ninguna migración agrega (de la primera versión del DDL) y
  que falte se reporta sin inventarle migración: la reparación es `\d` contra
  `crear_tablas.sql`.
- Mensajes al journal y a Kuma: sólo el tipo de la excepción y el SQLSTATE,
  nunca su texto (regla 5).
