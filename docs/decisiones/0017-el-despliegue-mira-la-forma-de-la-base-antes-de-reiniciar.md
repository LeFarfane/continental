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

## Enmienda 2026-09-21: informe.py

Esta decisión dejó a `src/continental/forma.py` importando de
`src/continental/verificar.py` lo único que las dos mitades puras necesitan
para hablar el mismo idioma: `Informe`, `Resultado`, `OK`/`FALLA`/`PENDIENTE`
y sus tres constructores (`_ok`, `_falla`, `_pendiente`). El préstamo era de
lo **privado** de un módulo hacia otro —`from continental.verificar import
_falla, _ok, ...`—, y por eso `verificar.py` nunca pudo importar `forma.py`
arriba del archivo: `correr()` y `main()` lo traían adentro de la función, dos
veces, sólo para no cerrar el círculo.

Se saca ese vocabulario a `src/continental/informe.py`, un tercer archivo que
no conoce ni a `forma.py` ni a `verificar.py` — hay una prueba que lo exige
(`tests/test_informe.py`). Con eso, `forma.py` y `verificar.py` importan del
mismo sitio en vez de importarse entre sí, y `verificar.py` ya puede traer
`forma` arriba del archivo: nada de lo que `forma.py` hace al cargarse toca
Postgres —el `motor()` sigue detrás de su propio `import` perezoso, adentro de
`forma.correr()`, igual que siempre— así que la regla de este mismo ADR de
"las importaciones que abren algo van dentro de la función" sigue firme,
sólo que ahora `forma` no es una de las que abre algo al cargarse.

De paso, el comando `cd ~/proyectos/Continental && .venv/bin/python -m
continental.verificar --forma` —que `forma.py` y `verificar.py` traían escrito
dos veces, a mano, con las mismas palabras— pasa a ser `COMANDO_FORMA`, una
constante de `informe.py` que los dos citan. La conducta pública de
`python -m continental.verificar`, con o sin `--forma`, no cambió: mismo
texto, mismo código de salida.

## Enmienda 2026-09-21: verificación diaria

**El hueco que quedaba.** `continental.verificar` —la corrida completa, forma
más invariantes de datos— solo corría en dos momentos: a mano, o como paso 7/7
de `scripts/desplegar.sh`. Los dos dependen de que **alguien despliegue**. Si
pasan varios días sin un `git push` —y nada obliga a que los haya todos los
días—, un invariante que se rompió (una migración a medias corrida a mano por
fuera del flujo normal, un GRANT que `dbt build` se llevó por delante, dos
listas abiertas el mismo día por un dato capturado a mano) se queda sin que
nadie lo mire hasta el próximo despliegue. El propio texto del módulo ya lo
decía sin sacar la consecuencia: *"pytest dice que el código hace lo que dice;
esto dice que los datos de producción están sanos"* — y "esto" solo corría
cuando el código cambiaba, no cuando los datos podían haber cambiado solos.

**La decisión.** Un timer de systemd, `continental-verificar.timer`, que
dispara `continental-verificar.service` (`Type=oneshot`) **todos los días**
—no solo lun-vie, porque un dato se puede romper cualquier día de la semana,
no solo los que corre la cadena de farmacia-data— y ejecuta
`python -m continental.verificar --latido`: la misma verificación completa de
siempre, con una única adición, `--latido`, que manda el veredicto a un
**segundo monitor propio** de Uptime Kuma
(`KUMA_PUSH_URL_VERIFICAR`/`VARIABLE_DEL_LATIDO_VERIFICAR` en
`src/continental/latido.py`, distinto del que ya tenía el lote,
`KUMA_PUSH_URL_CONTINENTAL`). Un monitor compartido con el lote confundiría
"los datos están rotos" con "el lote no trajo precios", que son dos preguntas
distintas con reparaciones distintas — la misma razón, aplicada otra vez, por
la que el ticket 19 le dio monitor propio al lote frente a los de
farmacia-data y Marlowe.

**Solo señala, nunca bloquea.** Este timer no reinicia `continental-web.service`,
no toca el lote y no repara un solo dato: es exactamente la misma regla que ya
regía el paso 7/7 de `desplegar.sh` (*"señala y no repara"*, y *"un dato roto
no tiene por qué impedir que un código bueno llegue"*), aplicada ahora a una
corrida que no depende de que nadie despliegue nada.

**La hora: 23:30, todos los días.** Dos colchones, razonados enteros en
`scripts/systemd/continental-verificar.timer`:

- **90 minutos después de la cadena de las 20:30** —el mismo colchón que el
  ADR 0006 ya midió y justificó para el lote—, porque `dbt build` recrea los
  modelos de `marts` y **se lleva los permisos por delante** en cada corrida:
  una lectura de esta verificación en medio de esa ventana vería
  `permission denied` de forma transitoria y mandaría un `down` falso sobre
  una base que en realidad está sana. Eso pone el piso en las 22:00.
- **Después del peor caso del lote**, que dispara a las 22:00 lun-vie y puede
  seguir vivo hasta las 23:15 (`TimeoutStartSec=75min`). No hay un motivo
  técnico fuerte para que las dos corridas no puedan convivir —esta
  verificación solo lee y el lote solo habla con Doyle y escribe sus propias
  filas—, pero evitar la coincidencia evita tener que defender esa afirmación
  cada vez que alguien mire el journal de esa franja.

23:30 cumple las dos cuentas con margen (quince minutos sobre el peor caso del
lote) y cae bien fuera del horario de mostrador de la farmacia, que es la otra
cara de la regla de farmacia-data *"nunca una consulta pesada sobre producción
en horario de operación"*. **Dicho con todas sus letras, porque importa para
lo que sigue: lo que corre aquí no es pesado.** `continental.verificar` hace
una decena de `SELECT 1 ... LIMIT 1` y unas pocas lecturas de las tablas
propias de `pedidos` —pequeñas, no las ~460 mil filas de farmacia-data—, y el
paso 7/7 de `desplegar.sh` ya ejecuta exactamente esto mismo en cada
despliegue, a cualquier hora del día, sin que eso haya sido nunca un problema.
Correrlo de madrugada es la postura conservadora, no una que haga falta
defender caso por caso.

**`Persistent=true`, al revés que el lote, y a propósito.** El ADR 0006 dejó
al lote sin `Persistent` porque un atlas que arrancara a media mañana
dispararía cuatro navegadores contra los portales del dueño en horario de
mostrador: un costo real, hacia afuera, contra terceros. Esta corrida no tiene
ese costo — son lecturas de Postgres y un latido HTTP a un contenedor local —,
así que perderse un día entero de verificación por un atlas apagado a las
23:30 es exactamente el hueco que este timer existe para cerrar, y protegerlo
con la misma decisión que el lote habría sido copiar la forma sin copiar la
razón.

**Qué NO se decidió aquí.** Si algún día la verificación se vuelve más pesada
—por ejemplo si crece a mirar `EXPLAIN` de cada sentencia, la alternativa F
que este mismo ADR dejó para después— la hora y el `Persistent=true` hay que
revisarlos con los mismos ojos con que se revisó el lote: puede que a esa
verificación más pesada sí le convenga negarse a correr fuera de su ventana.
Hoy no le convenía inventarse esa restricción sobre un trabajo que tarda
segundos.

**Consecuencias.**

- `desplegar.sh` **no instala ni refresca** `continental-verificar.{service,timer}`,
  el mismo trato que ya recibía la unidad del lote: el script despliega
  código, no unidades de systemd. Instalarlas es un paso de dueño, documentado
  en `docs/despliegue-en-atlas.md`, parte A.9.
- El código que la unidad ejecuta llega solo con cada `git pull`, sin
  reinstalar nada: `Type=oneshot` arranca un proceso nuevo en cada disparo.
- `.env.example` gana `KUMA_PUSH_URL_VERIFICAR`, vacía y comentada, con la
  misma frontera que ya separaba `WAREHOUSE_URL` y `KUMA_PUSH_URL_CONTINENTAL`
  del YAML versionado: el token es un secreto y vive solo en `.env`.
- `src/continental/latido.py` deja de tener la variable del monitor cableada:
  `url_del_latido` y `mandar_el_latido` reciben `variable` por argumento, con
  el valor de siempre como omisión, para poder servir a los dos monitores sin
  que uno tenga que conocer el nombre del otro.
