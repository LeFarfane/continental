# Propuesta — que el despliegue sepa si la base tiene la forma que el código espera

**Fecha:** 2026-09-21  ·  **Estado:** aceptada (C + D, E sólo en el lote, y G) — ver ADR 0017  ·  **Rama:** `pedido-sugerido`

Esto no es un ADR todavía. Es el material para escribirlo: el hueco, siete
maneras de cerrarlo con lo que cada una detecta y lo que no, y una
recomendación. No se tocó código.

---

## 1. El hueco, con sus eslabones

1. Las migraciones `0006` a `0011` (tickets 21 a 27) **agregan columnas**. El
   código nuevo las nombra en sus sentencias: `_LEER_RENGLONES` y
   `_LEER_RENGLON_POR_ID` piden `capturado_por`, `ventas_desde`,
   `cancelado_por`, `recibido_por`, `piezas_recibidas`, `piezas_que_faltaron`…;
   `_LEER_PEDIDOS` pide `enviado_por` y `cancelado_por`; `_INSERTAR_RENGLONES`
   escribe `piezas_que_faltaron` (todo en `src/continental/almacenamiento.py`).
2. Con la base sin migrar, la primera lectura de la lista rebota con
   `column ... does not exist` y la pantalla dice "no se pudo armar el pedido
   sugerido". El lote de las 22:00 (`continental-lote.service`) se corta igual.
3. `scripts/desplegar.sh` no lo ve en ningún paso:
   - el paso 3 (`pytest`) corre sin Postgres, a propósito;
   - el paso 5 (`/api/salud`) "no toca la base", a propósito;
   - el paso 6 (`python -m continental.verificar`) hace `SELECT 1` sobre las
     tablas y revisa invariantes sobre las filas. **Y corre después del
     reinicio del paso 4**: aunque viera algo, el código nuevo ya estaría
     sirviendo.
4. Lo único que hoy mira las columnas es `sql/verificar_rol.sql`
   (comprobaciones 28 a 37), que se corre **a mano, con credenciales de
   dueño**. Es exactamente la mitad de la tabla de la cabecera de
   `verificar.py` que no corre sola.

### Un hallazgo de paso: `verificar` sí ve una de esas columnas y la calla

`_filas_de_los_invariantes` hace `select * from pedidos.pedido` y le pasa las
columnas reales a `revisar_pedidos_enviados`. Si falta `enviado_por` —la base
sin la `0006`— el resultado es **`PENDIENTE`, que no tumba el despliegue**. Eso
era correcto en el ticket 17, cuando la columna "llegaba con otro ticket". Desde
el ticket 21 el código **ya la nombra**, así que su ausencia ya no es "falta un
ticket" sino "falta una migración", y el `PENDIENTE` convierte ese hueco en una
línea gris y un código de salida cero. Cualquiera de las alternativas de abajo
debería, además, dejar de tratar ese caso como pendiente (o dejárselo al
chequeo nuevo y decirlo en el mensaje).

### Lo que no se negocia

- **ADR 0003**: el rol `continental` no hace DDL; las migraciones las corre una
  persona con credenciales de dueño, nunca el servicio ni el arranque.
- **Regla 6**: el rol escribe solo sus tablas; de lo demás, solo lee lo que
  necesita.
- **Regla 4**: falla ruidoso. **Regla 5**: el detalle del error va a la consola
  o al journal, no al navegador.
- **Regla 7**: toda tabla dice a qué negocio pertenece (`negocio`), y
  `tests/test_sql_del_pedido.py::test_toda_tabla_dice_a_que_negocio_pertenece`
  lo exige tabla por tabla.
- Nada pesado ni vectorizado: atlas es un Athlon II de 2010.
- El suite **nunca** toca Postgres.

### Un hecho que abarata casi todo: la columna es testigo de su migración

Las once migraciones tienen la misma forma: guardia `DO $guardia$` que se niega
a correr como `continental`, `BEGIN;`, sentencias idempotentes
(`ADD COLUMN IF NOT EXISTS`, `DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT`),
`COMMIT;`, y luego un `SELECT` informativo. **Todas agregan al menos una
columna o crean una tabla, dentro de la transacción.** Así que si la columna
está, el resto de esa migración —sus CHECK ampliados, sus rellenos— también
entró: una transacción no se queda a medias.

| Migración | Testigo (tabla.columna) |
|---|---|
| 0001 | `renglon.descartado_por` |
| 0002 | `renglon.cantidad_final` |
| 0003 | la tabla `precio_de_proveedor` (p. ej. `precio_como_llego`) |
| 0004 | la tabla `corrida_del_lote` (p. ej. `termino_en`) |
| 0005 | `pedido.proveedor`, `renglon.proveedor_elegido` |
| 0006 | `pedido.enviado_por` |
| 0007 | `renglon.capturado_por` |
| 0008 | `renglon.ventas_desde` |
| 0009 | `pedido.cancelado_por`, `renglon.cancelado_por` |
| 0010 | `renglon.recibido_por`, `renglon.compras_rechazadas` |
| 0011 | `renglon.piezas_recibidas`, `renglon.piezas_que_faltaron` |

Esto quiere decir que **las seis migraciones sin marca ya dejaron una marca**:
la forma misma de la tabla. Las alternativas que leen la forma no necesitan
rellenar nada; las que leen una etiqueta sí.

---

## 2. Las alternativas

Para cada una: cómo funciona, qué detecta y qué no, cómo se lleva con el ADR
0003, qué cuesta, qué pasa con las seis que ya existen y cómo se prueba sin
Postgres.

### A. Una tabla `pedidos.migracion` con el número de cada migración

**Cómo funciona.** Una tabla nueva, poseída por `farmacia`. Cada migración,
antes de su `COMMIT;`, inserta su número. El código declara
`MIGRACION_QUE_NECESITA = 11` y un chequeo compara contra `max(numero)`.

```sql
CREATE TABLE IF NOT EXISTS pedidos.migracion (
    numero      integer     PRIMARY KEY CHECK (numero > 0),
    archivo     text        NOT NULL,
    corrida_en  timestamptz NOT NULL DEFAULT now(),
    corrida_por text        NOT NULL DEFAULT current_user
);
GRANT SELECT ON pedidos.migracion TO continental;

-- al final de cada migración, dentro de la transacción:
INSERT INTO pedidos.migracion (numero, archivo)
VALUES (12, '0012-...') ON CONFLICT (numero) DO NOTHING;
```

**Detecta:** que no se corrió una migración que el código declara necesitar.
Y deja historia: quién y cuándo.

**No detecta:** nada que no sea la etiqueta. Un `ALTER TABLE ... DROP COLUMN`
a mano, una migración editada después de correrse, o una fila insertada a
mano sin correr la migración dan verde. Es el problema que la cabecera de
`verificar.py` ya nombra con otras palabras —"el catálogo contesta lo que el
catálogo cree"—, sólo que peor: aquí contesta lo que alguien escribió.
Tampoco detecta que `MIGRACION_QUE_NECESITA` se quedó sin subir.

**ADR 0003.** No choca en la escritura: la fila la inserta la migración, que
corre como dueño; el rol solo necesita `SELECT`. **Choca con otras dos cosas**:
es una **sexta tabla** (la comprobación 4 de `verificar_rol.sql` cuenta cinco a
mano a propósito, `test_estan_las_cinco_tablas_y_ninguna_mas` también, y el ADR
dice que agregar una tabla "es un acto deliberado"), y **no tiene `negocio`**
—una migración es de la base, no de una farmacia—, así que rompe la regla 7 o
la obliga a una excepción escrita.

**Cuesta.** Una migración `0012` que crea la tabla; volver a correr
`crear_rol.sql` (tabla nueva sin GRANT, lo mismo que le pasó a
`precio_de_proveedor` con la `0003`); tocar la comprobación 4 y los tests que
cuentan cinco; una constante en Python; un `INSERT` en cada migración futura.
Unas 40 líneas de Python y 6–8 pruebas, más el ajuste de las que cuentan tablas.

**Las seis que ya existen.** No dejaron fila. La `0012` tendría que rellenar
de 1 a 11 **por evidencia**, no por fe:

```sql
INSERT INTO pedidos.migracion (numero, archivo)
SELECT m.numero, m.archivo
  FROM (VALUES (1, '0001-renglon-quien-descarto-y-cuando.sql',   'renglon', 'descartado_por'),
               (6, '0006-enviar-el-pedido.sql',                  'pedido',  'enviado_por'),
               (11,'0011-recibido-parcial-y-a-mano.sql',         'renglon', 'piezas_que_faltaron')
               -- … las once, con los testigos de la tabla de arriba
       ) AS m(numero, archivo, tabla, testigo)
 WHERE EXISTS (SELECT 1 FROM pg_attribute a
                WHERE a.attrelid = to_regclass('pedidos.' || m.tabla)
                  AND a.attname  = m.testigo
                  AND NOT a.attisdropped)
ON CONFLICT (numero) DO NOTHING;
```

O sea: para rellenar la etiqueta hay que leer la forma. Si la forma ya es la
evidencia, la etiqueta es una segunda copia.

**Sin Postgres.** Se prueba la mitad pura (`revisar_migracion(numero_en_la_base,
numero_que_necesita) -> Informe`) y que `MIGRACION_QUE_NECESITA` sea igual al
número más alto de `sql/migraciones/*.sql` (leyendo los nombres de archivo), y
que cada migración a partir de la 0012 contenga su `INSERT INTO
pedidos.migracion` con su propio número.

### B. `COMMENT ON SCHEMA pedidos` con la versión

**Cómo funciona.** Cada migración termina con un `COMMENT ON SCHEMA pedidos IS
'… · forma 0012'`; `crear_tablas.sql` pone el de la última. El chequeo lee
`obj_description('pedidos'::regnamespace, 'pg_namespace')` y extrae el número
con una expresión regular.

**Detecta:** lo mismo que A, sin historia.

**No detecta:** lo mismo que A, y además es texto libre: el comentario de hoy
es **lo único que dice a qué proyecto pertenece el esquema** (ADR 0003,
"Consecuencias"), y cada migración lo reescribiría entero. Un comentario
editado a mano, o una migración que copie mal la frase, rompe el parseo o
—peor— lo deja parsear otro número.

**ADR 0003.** No choca: `pg_description` es legible por cualquier rol y no hace
falta GRANT, tabla nueva ni `negocio`. `COMMENT ON` lo corre el dueño.

**Cuesta.** Casi nada en SQL (una línea por migración); unas 25 líneas de
Python y 4–5 pruebas. Pero cada migración futura tiene que reescribir un texto
de cuatro renglones sin equivocarse.

**Las seis que ya existen.** Un `COMMENT ON SCHEMA` a mano, una vez, después de
confirmar con `verificar_rol.sql` que la 28–37 salen `[BIEN]`. Es relleno por
fe: nada impide ponerlo sin haber mirado.

**Sin Postgres.** Pura: `version_en_el_comentario(texto) -> int | None` y
`revisar_version(...)`. Y un test que exija que `crear_tablas.sql` y la última
migración pongan el mismo número.

### C. Comparar las columnas reales contra las que `crear_tablas.sql` declara

**Cómo funciona.** La lista esperada **no se escribe a mano**: se saca de
`sql/crear_tablas.sql`, que el ADR 0003 define como "la forma a la que se
quiere llegar". La lista real se saca **leyendo como el rol**:
`select * from pedidos.<tabla> limit 0` y las claves del resultado —la misma
técnica que ya usan `columnas_de_dim_producto` y `_filas_de_los_invariantes`—.
La diferencia se traduce a "corre esta migración" leyendo los `ADD COLUMN` y
`CREATE TABLE` de `sql/migraciones/*.sql`.

Piezas, en un módulo nuevo `src/continental/forma.py` (o dentro de
`verificar.py`, ver la recomendación):

```python
def columnas_de_crear_tablas(sql: str) -> dict[str, frozenset[str]]:
    """{'renglon': {...}, 'pedido': {...}, ...} — el cuerpo de cada
    CREATE TABLE IF NOT EXISTS pedidos.<t> ( ... ); sin comentarios `--`,
    partido por comas de primer nivel, sin las líneas CONSTRAINT/PRIMARY/
    UNIQUE/CHECK/FOREIGN."""

def migracion_de_cada_columna(migraciones: dict[str, str]) -> dict[tuple[str, str], str]:
    """{('renglon', 'piezas_que_faltaron'): '0011-recibido-parcial-y-a-mano.sql', ...}
    de los ALTER TABLE pedidos.<t> ... ADD COLUMN IF NOT EXISTS <c>, y de las
    columnas de los CREATE TABLE que hacen la 0003 y la 0004."""

def revisar_forma(esperadas, reales, de_que_migracion) -> Informe:
    """FALLA por tabla con columnas de menos, y la reparación es el comando
    `docker exec -i ... < sql/migraciones/NNNN-*.sql` de CADA migración que
    falta, en orden y sin repetir. PENDIENTE (no falla) si la base tiene
    columnas DE MÁS: la base va adelante del código, que es legítimo —las
    migraciones solo agregan— y a media semana es lo normal."""

def columnas_reales(motor, tablas) -> dict[str, frozenset[str]]:
    """Recolección. `select * from pedidos.<t> limit 0` por tabla, cada una en
    su transacción, como `_intentar_leer`. No se prueba."""
```

**Detecta:** cualquier columna que el esquema declarado tiene y la base no; por
el argumento del testigo (§1), eso es "no se corrió la migración NNNN", y lo
dice con el archivo exacto. También una tabla entera que falta (la 0003 o la
0004 sin correr). Y un `DROP COLUMN` a mano, que A y B no ven.

**No detecta:**

- **Tipos, nulabilidad y CHECK.** Una columna `numeric` que quedó `integer`, o
  un `ck_pedido_estado` al que alguien le quitó `'cancelado'` a mano. Eso sigue
  siendo de `verificar_rol.sql`. Para lo que traen las migraciones no hace
  falta: el CHECK viaja en la misma transacción que su columna.
- **Que el código nombre una columna que `crear_tablas.sql` no declara.** Eso
  es un error de los archivos, no de la base, y no se ve aquí; se ve en el
  suite si se agrega la prueba de coherencia de la alternativa G.
- **Nada fuera de `pedidos`.** Si `dbt` renombra una columna de `marts`, esto no
  lo ve (hoy tampoco; ver la alternativa F).

**ADR 0003.** No choca. Es una lectura, con el rol acotado, sobre las cinco
tablas a las que ya tiene `SELECT`; no escribe nada y no consulta el catálogo.
Si alguien prefiere el catálogo: **sí, el rol puede leer `information_schema`**
—`information_schema.columns` le muestra las columnas de las tablas sobre las
que tiene algún privilegio, que son justo sus cinco— y `pg_attribute` es
legible por `PUBLIC`. Pero leer como el rol es lo que la casilla 5 del ticket
17 eligió y sirve igual: `limit 0` trae las claves sin traer filas.

**Cuesta.** Ninguna migración, ninguna tabla, ningún GRANT. Unas 120–150 líneas
de Python (el parseo de `crear_tablas.sql` es la mitad) y unas 12 pruebas. Cero
trabajo en cada migración futura: la migración nueva agrega su `ADD COLUMN` y
`crear_tablas.sql` agrega la columna —las dos cosas que el ADR 0003 ya exige—,
y el chequeo las aprende solo.

**Las seis que ya existen.** No hay que hacer nada. Sus columnas son la marca.

**Sin Postgres.** Todo lo que decide es puro y se alimenta con texto:

- `columnas_de_crear_tablas(Path('sql/crear_tablas.sql').read_text())` devuelve
  exactamente las cinco tablas de `test_estan_las_cinco_tablas_y_ninguna_mas`,
  y `renglon` contiene cada columna de las `select` de `_LEER_RENGLONES`.
- `migracion_de_cada_columna` sobre los once archivos reales: toda columna que
  una migración agrega está en `crear_tablas.sql` (la regla de "dos archivos" del
  ADR 0003, ahora comprobada), y `('renglon', 'piezas_que_faltaron')` apunta a
  la 0011.
- `revisar_forma` con diccionarios en memoria: la forma completa da `ok`; quitar
  `enviado_por` da FALLA con `0006-enviar-el-pedido.sql` en la reparación;
  quitar columnas de la 0009 y la 0011 da las dos, en orden; una columna de más
  da PENDIENTE y código de salida cero.
- Las mismas guardas que `test_verificar.py` ya aplica: importar el módulo no
  abre nada y ninguna función pura nombra un motor.

### D. Mover el chequeo **antes** del reinicio en `desplegar.sh`

**Cómo funciona.** No es un mecanismo de detección: es **dónde** corre. Hoy
`verificar` es el paso 6, después del `systemctl restart`, y así debe seguir
para los **datos** (el ticket 17 lo razona: un dato roto no tiene por qué
impedir que un código bueno llegue). Pero la **forma** es otra pregunta —¿este
código puede correr contra esta base?— y ésa sí tiene que impedir el reinicio.

```bash
paso "4/7  la base tiene la forma que este código espera"
if ! "$PYTHON" -m continental.verificar --forma; then
    echo "    !! NO se reinicia nada; el servicio sigue con el código anterior."
    echo "       El código nuevo YA está en disco (paso 1): el lote de las 22:00"
    echo "       lo va a usar. Corre arriba las migraciones que se nombran ANTES"
    echo "       de esa hora, y vuelve a correr este script."
    exit 1
fi

paso "5/7  reinicio de $SERVICIO"   # los demás pasos se renumeran
```

**Detecta:** lo que detecte el mecanismo que se ponga ahí (A, B, C o F). Sola,
nada.

**No detecta / su trampa.** El `git pull` del paso 1 **ya dejó el código nuevo
en disco**. El servicio web sigue con el viejo en memoria, pero
`continental-lote.service` ejecuta `python -m continental.lote` desde el repo,
así que a las 22:00 corre el código nuevo contra la base vieja, y un reinicio
por caída del web también lo levantaría. Por eso el mensaje lo dice y por eso
conviene la variante de la alternativa E para el lote.

Por qué el viejo con la base nueva sí funciona, que es lo que hace útil este
orden: las migraciones **solo agregan** (columnas que admiten nulos o traen
`DEFAULT`, CHECK ampliados), así que el orden correcto es "migrar, luego
desplegar", y el código anterior sigue leyendo sin enterarse.

**ADR 0003.** No choca: el script ya corre `verificar` con el `.env` del rol.

**Cuesta.** Unas 10 líneas en `desplegar.sh` y un argumento `--forma` (o un
`python -m continental.forma`). En pruebas:
`test_los_pasos_van_en_el_orden_del_ticket` pasa de `N/6` a `N/7` y agrega que
`-m continental.verificar --forma` quede **antes** de `systemctl restart`;
`test_el_verificador_de_datos_va_al_final_y_despues_de_la_salud` sigue igual
para la corrida sin `--forma`. La prueba de rótulos ya exige que se ajusten
todos o ninguno.

**Las seis que ya existen.** Lo que diga el mecanismo elegido.

**Sin Postgres.** Como el resto de `test_despliegue.py`: leyendo el texto del
script (posiciones relativas de `--forma`, `systemctl restart` y `curl`, y que
el bloque tenga `exit 1`).

### E. Que el arranque se niegue a levantar con un esquema que no cuadra

**Cómo funciona.** `iniciar.py --servicio` llama al chequeo de forma antes de
`uvicorn.run`; si falla, imprime el informe al journal y sale con código
distinto de cero. systemd reintenta hasta `StartLimitBurst` y la deja en
`failed`.

**Detecta:** lo que el mecanismo de dentro, y **también cuando nadie usó
`desplegar.sh`** (un reinicio a mano, un reinicio de atlas).

**No detecta / su precio.**

- **Convierte una falla parcial en una total.** Hoy, con la base vieja, la
  lista del día no carga pero `/api/salud`, los módulos y lo que no dependa de
  `pedidos` siguen. Con esto, `farmacia.farfanlab.uk` da 502 entero. La regla 4
  pide "un hueco con su motivo", no apagar la puerta.
- **Llega tarde**: corre después del reinicio, que es cuando ya se perdió el
  código viejo que funcionaba.
- **Mezcla dos fallas.** Si al arrancar atlas el contenedor del almacén todavía
  no contesta, "no pude preguntar" no puede tratarse como "no cuadra" o el
  servicio no levantaría nunca tras un corte de luz; y tratarlo distinto es
  justo la clase de rama que se prueba mal.
- **Contradice cómo está hecho el web**: el motor es perezoso a propósito y
  `/api/salud` "no toca la base".

**La variante que sí vale: el lote.** `continental.lote` es un proceso por
lotes, sin nada parcial que perder. Si al empezar corre el mismo chequeo de
forma y, si no cuadra, sale con su motivo en el journal **antes** de armar la
lista, se cierra el hueco que deja D (código nuevo en disco, base vieja, 22:00).
Unas 10 líneas en `lote.py` y 2 pruebas con dobles.

**ADR 0003.** No choca mientras sólo **lea**. Chocaría de frente si alguien
convierte "se niega a arrancar" en "aplica lo que falta al arrancar": eso es
exactamente el `preparar()` que el ADR prohíbe, y el rol ni siquiera podría.

**Cuesta.** Poco código, pero cambia el modo de falla del servicio entero y
toca `test_despliegue.py` (arranque) y la unidad.

**Las seis que ya existen.** Lo que diga el mecanismo de dentro.

**Sin Postgres.** Inyectando una función de chequeo falsa en `iniciar.main` (el
mismo estilo que `tests/test_despliegue.py` usa con el puerto ocupado) y
comprobando que sale con código distinto de cero y no llama a `uvicorn.run`.

### F. Ensayar en seco las sentencias del código con `EXPLAIN`

**Cómo funciona.** En vez de comparar listas, se le pregunta a Postgres si
**puede planear cada sentencia que el código de verdad ejecuta**. Se recorren
las constantes `text(...)` de `almacenamiento.py` (y de los otros módulos que
escriben en `pedidos`) y por cada una se corre `EXPLAIN <sentencia>` con
parámetros de relleno, en una transacción que se revierte. `EXPLAIN` sin
`ANALYZE` **no ejecuta nada** —tampoco un `INSERT` o un `UPDATE`— pero sí
resuelve cada columna, cada tabla y cada `ON CONFLICT ON CONSTRAINT`.

**Detecta:** lo que ninguna otra detecta sin duplicar listas: la columna que el
código nombra y la base no tiene, **aunque `crear_tablas.sql` tampoco la
declare**; la restricción nombrada en `_ABRIR_EL_PEDIDO`
(`ux_pedido_proveedor`) si no existe; y columnas de `marts` que `dbt` haya
renombrado. La lista esperada es el código mismo: cero copias.

**No detecta:** los valores que acepta un CHECK (`'cancelado'` fuera de
`ck_pedido_estado` sólo truena al ejecutar), tipos que casan por conversión
implícita, ni sentencias armadas en tiempo de ejecución que no sean
constantes de módulo.

**Riesgos que hay que medir en atlas antes de confiar.** Los parámetros de
relleno: psycopg2 interpola del lado del cliente, así que un `None` llega como
`NULL` literal, y algunas posiciones pueden quejarse del tipo (`= any(:renglon_ids)`,
aritmética de fechas). Hay que clasificar por `SQLSTATE`: `42703`
(`undefined_column`), `42P01` (`undefined_table`) y `42704`
(`undefined_object`) son "la base no tiene la forma"; cualquier otro error es
**falla de la sonda**, dicha como tal y con la sentencia nombrada, nunca un
verde. Puede hacer falta un diccionario `VALORES_DE_ENSAYO` para las pocas
sentencias que lo pidan. Nada de esto se puede probar desde la torre.

**ADR 0003.** No choca: `EXPLAIN` no escribe, y los permisos que comprueba son
los que el rol ya tiene. No hace DDL.

**Cuesta.** Unas 80 líneas y 8 pruebas, más una primera corrida vigilada en
atlas. La reparación es menos precisa que en C: el error dice la columna, no la
migración (se puede cruzar con `migracion_de_cada_columna` de C).

**Las seis que ya existen.** Nada que hacer.

**Sin Postgres.** Pura: `sentencias_del_codigo(modulo) -> dict[str, str]` (que
encuentre todas las constantes `text(...)` — contrastado contra un conteo por
`ast` del mismo archivo, para que una constante nueva no se escape) y
`revisar_ensayo(resultados: list[tuple[nombre, sqlstate | None]]) -> Informe`.

### G. Coherencia de los archivos, en el suite (complemento, no solución)

**Cómo funciona.** Una prueba que, sin base, cruza tres textos: las columnas
que nombran las `select`/`insert`/`update` de `almacenamiento.py`, las que
declara `crear_tablas.sql` y las que agregan las migraciones.

**Detecta:** que alguien agregó una columna al código y a la migración pero no
a `crear_tablas.sql` (o al revés) — el error que dejaría a C comparando contra
una forma incompleta.

**No detecta:** nada de la base de atlas. Es el cinturón de C, no su reemplazo.

**Cuesta / ADR / las seis / sin Postgres.** Unas 60 líneas de prueba y un
extractor de identificadores deliberadamente tosco (tokens de la lista del
`select` y del `set`); no toca el ADR; las seis ya están en `crear_tablas.sql`
(lo exigen `test_parcial.py`, `test_captura.py` y compañía, una por una), así
que esto generaliza pruebas que hoy se escriben a mano por ticket.

---

## 3. En una tabla

| | Qué mira | Ve un `DROP COLUMN` a mano | Toca el ADR 0003 | Trabajo por migración futura | Las seis que ya existen |
|---|---|---|---|---|---|
| A. tabla de migraciones | una etiqueta | no | sexta tabla, sin `negocio` | un `INSERT` + subir la constante | relleno por testigo |
| B. comentario del esquema | una etiqueta | no | no | reescribir el comentario | relleno a mano, por fe |
| C. columnas vs `crear_tablas.sql` | la forma | **sí** | no | **ninguno** | **nada** |
| D. antes del reinicio | (dónde, no qué) | — | no | ninguno | — |
| E. el arranque se niega | (dónde, no qué) | — | no, si sólo lee | ninguno | — |
| F. `EXPLAIN` del código | lo que el código ejecuta | sí | no | ninguno | nada |
| G. coherencia en el suite | los archivos | — | no | ninguno | ya cubiertas |

---

## 4. Recomendación

**C + D, con la variante del lote de E y la prueba G; F queda como segundo
paso cuando haya una corrida medida en atlas.** C es la única que mira la
forma y no una etiqueta, no agrega tabla ni GRANT ni trabajo a cada migración,
y resuelve las seis migraciones existentes sin rellenar nada, porque sus
columnas ya son la marca y cada migración es una sola transacción. D lo pone
donde sirve: antes del `systemctl restart`, fallando duro y sin mover los
invariantes de datos, que siguen en el paso final y sin bloquear. La variante
de E en `continental.lote` tapa el único agujero que D deja (el código ya está
en disco tras el `git pull` y el timer de las 22:00 lo usa), y G impide que C
compare contra un `crear_tablas.sql` incompleto. A y B se descartan porque
guardan una afirmación en lugar de mirar el hecho, y para rellenarlas con
honestidad hay que leer la forma de todos modos. E aplicada al web se descarta
porque convierte la falla de una pantalla en la caída de la puerta entera y
llega después del reinicio. F es la más completa, pero su parte frágil (los
parámetros de relleno) sólo se puede medir en atlas, así que conviene que
entre después, sobre un chequeo C ya en verde.

De paso, `revisar_pedidos_enviados` debería dejar de reportar como `PENDIENTE`
la falta de `estado` o `enviado_por` (§1): con C en el paso previo al reinicio,
ese caso ya no llega vivo al paso 6, y si llega, es una falla y no un ticket
pendiente.

### Lo que tocaría el cambio (para el ticket que lo implemente)

- `src/continental/verificar.py`: `columnas_de_crear_tablas`,
  `migracion_de_cada_columna`, `revisar_forma` (puras) y `columnas_reales`
  (recolección); `main` acepta `--forma` y corre sólo eso. La tabla de la
  cabecera gana una tercera columna: **la forma, leída como el rol, en cada
  despliegue, antes del reinicio**.
- `src/continental/lote.py`: al empezar, la misma comprobación; si falla, sale
  con el informe en el journal y sin armar lista.
- `scripts/desplegar.sh`: el paso nuevo `4/7`, los rótulos a `N/7`.
- `tests/test_verificar.py` (o `tests/test_forma.py`), `tests/test_despliegue.py`,
  `tests/test_lote.py`, y la prueba de coherencia G en
  `tests/test_sql_del_pedido.py`.
- Un ADR nuevo en `docs/decisiones/` que registre esto y las alternativas
  descartadas.

### Lo que el dueño corre a mano en atlas si la acepta

**Nada nuevo en SQL.** La alternativa recomendada no crea tabla, no cambia
permisos y no pide migración. Lo único es ponerse al día con lo que ya estaba
pendiente, desde `~/proyectos/Continental` y con credenciales de dueño, **antes**
de desplegar el código que trae el chequeo (si no, el primer despliegue con el
chequeo se detendrá en el paso `4/7` y nombrará estas mismas migraciones, que
es justo lo que se quiere):

```bash
cd ~/proyectos/Continental
for m in sql/migraciones/0006-*.sql sql/migraciones/0007-*.sql \
         sql/migraciones/0008-*.sql sql/migraciones/0009-*.sql \
         sql/migraciones/0010-*.sql sql/migraciones/0011-*.sql; do
    echo "==> $m"
    docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
        -v ON_ERROR_STOP=1 < "$m" || break
done

docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
    -v ON_ERROR_STOP=1 < sql/verificar_rol.sql ; echo "salida: $?"
```

Son idempotentes, así que correr una que ya estaba no hace daño; el `|| break`
detiene la cadena en la primera que falle (la `0011`, por ejemplo, se niega a
correr si hay un `recibido parcial` sin cifra, y eso lo decide una persona). Si
alguna de la `0001` a la `0005` tampoco se hubiera corrido, `verificar_rol.sql`
lo dirá, y la `0003` y la `0004` además piden volver a correr `crear_rol.sql`.

Después, el despliegue de siempre:

```bash
~/proyectos/Continental/scripts/desplegar.sh
```

y comprobar que el paso `4/7` dice que la forma cuadra antes de que aparezca
el reinicio.

Si en lugar de esto se eligiera **A**, lo que habría que correr a mano es la
migración `0012` (tabla, GRANT y relleno por testigo), luego `crear_rol.sql` y
luego `verificar_rol.sql`, con su comprobación 4 ya ajustada a seis tablas.
