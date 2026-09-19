# 0008 — El pedido se identifica por la clave de Doyle, y el proveedor de SICAR es una correspondencia que puede faltar

**Fecha:** 2026-09-19  ·  **Estado:** aceptada

## Contexto

El ticket 20 es el paso donde la comparación se vuelve una decisión: el
encargado marca a quién le pide cada renglón y la lista del día se convierte en
uno o varios pedidos. Para escribir la primera fila de `pedidos.pedido` hay que
resolver algo que **hasta hoy no existía en ninguna parte del proyecto**.

Hay **dos identidades de proveedor** en juego y nada las cruzaba:

| | Quién la pone | Dónde vive | Qué significa |
|---|---|---|---|
| `nadro`, `levic`, `vicma`, `quepharma` | Doyle | `precio_de_proveedor.proveedor` (ticket 12), `precios.NOMBRES_DE_PROVEEDOR`, `config/proveedores.yml` de Doyle | a quién se le preguntó el precio |
| `1`, `8`, `10`, … | SICAR | `marts.dim_proveedor.proveedor_id` (el `pro_id`) | a quién se le ha comprado |

La comparación entera —tickets 12 a 15— habla en claves de Doyle. La tabla
`pedidos.pedido`, escrita en el ticket 07, nació con
`proveedor_id bigint NOT NULL` apuntando a `marts.dim_proveedor`. **El puente no
estaba ni en `config/continental.yml`, ni en el código, ni en el SQL.** Era un
hueco silencioso: nada fallaba porque ningún código había escrito todavía en esa
tabla.

Cinco hechos delimitan el problema, y los cinco están medidos o escritos:

1. **`marts.dim_proveedor` tiene 22 filas** (leído en atlas el 2026-09-19).
   NADRO es el `1`, VICMA el `8` y LEVIC el `10`.
2. **QuePharma no está.** La farmacia nunca le ha comprado, así que SICAR no
   tiene una fila suya. No es un dato que falte por capturar: es un hecho del
   catálogo. Y el ADR 0002 ya daba por probable que QuePharma quedara fuera de
   la comparación por otro motivo (usa código interno y no está confirmado que
   encuentre por EAN).
3. **`dim_proveedor` la recrea `dbt build` cada noche.** Por eso
   `pedidos.pedido` ya nació **sin** llave foránea contra ella: una FK contra
   una tabla que se recrea o impide el `DROP` —y la cadena nocturna se cae por
   culpa de Continental— o desaparece con ella, que es peor porque nadie se
   entera.
4. **El rol `continental` no puede hacer DDL** (ADR 0003). Una tabla nueva
   cuesta `crear_tablas.sql`, una migración, **volver a correr `crear_rol.sql`**,
   `verificar_rol.sql` y `src/continental/verificar.py`. El ADR 0007 pagó ese
   precio entero hace un ticket y lo dejó escrito.
5. **`marts.dim_proveedor` ya está otorgada** en `sql/crear_rol.sql`, con su
   razón: *"el nombre del proveedor al que se le pide; sin esta tabla la
   pantalla diría «proveedor 3» en vez de «NADRO»"*. Hasta hoy ningún código la
   leía.

## Opciones consideradas

**Dónde vive el cruce**

1. **Un mapa en `config/continental.yml`**, clave de Doyle → `pro_id`.
2. **Una columna** en `pedidos.pedido` con la clave de Doyle, al lado del
   `proveedor_id`.
3. **Una tabla propia** en el esquema `pedidos`, con una fila por pareja.
4. **Cambiar el tipo de `proveedor_id` a `text`** y guardar ahí la clave de
   Doyle, tirando el id de SICAR.

**Qué pasa cuando el puente no existe para un proveedor**

- A. **No se puede pedir.** `proveedor_id` sigue `NOT NULL`.
- B. **Se pide igual**, con `proveedor_id` en `NULL`.
- C. Se pide igual, con un id inventado (un `0`, o una fila "otros").

## Decisión

**1 + 2 + B.** Las tres partes son una sola cosa y por eso van juntas:

- **`pedidos.pedido` gana `proveedor text NOT NULL`, la clave de Doyle, y ésa es
  la identidad del pedido.** `ux_pedido_proveedor` —"uno por proveedor dentro de
  la misma lista"— se mueve a esa columna.
- **`proveedor_id` pasa a admitir nulos** y queda como una **correspondencia**:
  a quién corresponde este proveedor en el catálogo de SICAR, cuando
  corresponde a alguien.
- **El mapa vive en `config/continental.yml`**, bajo
  `pedido.proveedores_en_sicar`, y se lee en `src/continental/proveedores.py`.
  **Guarda el `pro_id` y no el nombre.**

No se crea ninguna tabla: el esquema `pedidos` sigue teniendo cinco.

## Razones

### Por qué la identidad es la clave de Doyle

**Se le pide a quien se le preguntó el precio.** Todo lo que este módulo sabe de
un proveedor —su precio congelado, su existencia, su motivo de hueco, su sesión
caducada— está indexado por la clave de Doyle. El `pro_id` de SICAR solo aparece
al final, y solo para poder cruzar después la compra que llegue.

Si la identidad fuera el `proveedor_id`, **un proveedor sin fila en SICAR no se
podría pedir**. Eso no es una hipótesis incómoda: es el estado de QuePharma hoy.
El sistema estaría diciendo *"no le puedes comprar a quien nunca le has
comprado"*, que es exactamente al revés de cómo empieza una relación con un
proveedor nuevo.

Y hay una razón de esquema encima: `precio_de_proveedor.proveedor` ya guarda la
clave de Doyle. Con `pedido.proveedor` guardando lo mismo, **hay una sola
identidad de proveedor en todo el esquema** y el join entre el precio con el que
se decidió y el pedido que salió de esa decisión es directo.

### Por qué `proveedor_id` puede faltar, y por qué NULL y no un cero

`NULL` aquí significa *"SICAR no conoce a este proveedor"*, que es un hecho
verificable y no un dato pendiente.

La opción C —un `0`, o una fila "otros"— es la que hay que descartar con todas
sus letras porque es la que se propone sola cuando alguien quiere que la columna
siga siendo `NOT NULL`. **Un cero cabe en un `bigint` sin protestar**, y a
partir de ahí todo `join` contra `dim_proveedor` sale vacío **sin error**: no
hay fila, no hay excepción, no hay aviso. Es el mismo daño que un precio en cero
en la comparación —gana toda comparación de "el más barato" y dispara la compra
equivocada— y lo prohíbe la misma regla, la 4 de `CLAUDE.md`. Por eso el CHECK
es `proveedor_id > 0` y no `>= 0`.

### La trampa del UNIQUE, que es la mitad que se puede hacer mal sin que avise

`ux_pedido_proveedor` decía `UNIQUE (pedido_sugerido_id, proveedor_id)` y
sostenía la frase del glosario: *un pedido sugerido puede repartirse en varios
pedidos, uno por proveedor*.

**En cuanto `proveedor_id` admite nulos, esa restricción deja de sostener
nada.** En Postgres dos nulos no se consideran iguales dentro de un `UNIQUE`, así
que dos pedidos a QuePharma —los dos con `proveedor_id` en `NULL`— entrarían los
dos: dos veces la misma mercancía, sin un solo error que ver. Aflojar la columna
sin mover la restricción habría sido un cambio que se ve inocente en el diff y
rompe la garantía más importante del ticket.

Por eso el `UNIQUE` se mueve a `proveedor`, que es la columna que siempre vale
algo. Conserva el nombre porque sigue significando lo mismo, y porque
`almacenamiento._ABRIR_EL_PEDIDO` la nombra en su `ON CONFLICT ON CONSTRAINT`:
es lo que hace que **partir dos veces reencuentre el pedido que ya estaba en vez
de duplicarlo**. La comprobación 24 de `sql/verificar_rol.sql` lee la definición
de vuelta desde el catálogo.

**No se pone un `UNIQUE` sobre `proveedor_id`.** Dos claves de Doyle apuntando
al mismo `pro_id` sería un error del YAML, y la manera de atenderlo es el aviso
que `proveedores.leer_el_puente` escribe al arrancar — no un pedido que rebota
con una violación de restricción a media mañana y que, por la regla 5, el
encargado vería como "algo falló".

### Por qué el YAML y no una tabla

Una tabla en este repo cuesta el precio completo que el ADR 0007 enumeró:
`crear_tablas.sql`, una migración, **volver a correr `crear_rol.sql`** —un
`GRANT` no se puede dar sobre una tabla que no existía, y es el olvido que la
migración 0003 documentó—, `verificar_rol.sql` y `verificar.py`.

Lo que se guardaría son **cuatro parejas que no cambian nunca**, y que además no
son un hecho producido por el proceso: son **configuración de esta
instalación**, igual que a qué puerto vive Doyle o qué anaqueles cuentan como
medicamento. `config/continental.yml` ya existe exactamente para eso y ya se
versiona sin secretos.

La tabla valdría la pena el día que el cruce **cambiara solo** —que alguien lo
editara desde la pantalla, o que se dedujera de las compras— y ninguna de las
dos cosas está en ningún ticket.

### Por qué el mapa guarda el ID y no el nombre

Era la alternativa cómoda: `nadro: "NADRO"` y resolver el `proveedor_id` con un
`select ... where nombre = ...` al partir. **Se descartó porque no sobrevive a lo
que este ADR tiene que sobrevivir.**

- **Si SICAR renombra un proveedor** —corrige un acento, le agrega "S.A. de
  C.V."—, el `pro_id` **no cambia** y el puente por id sigue valiendo. Un puente
  por nombre se rompería en silencio: el `select` no encontraría nada y el
  pedido saldría sin `proveedor_id`, que se ve exactamente igual que QuePharma.
  Dos causas muy distintas con la misma pinta es justo lo que este repo
  persigue.
- Un `join` por nombre contra una tabla que `dbt build` recrea cada noche es,
  además, la misma clase de acoplamiento frágil que el ticket 07 ya rechazó al
  no poner la llave foránea.

El nombre se lee de `dim_proveedor` **cada vez y solo para pintarlo**, que es
para lo que el `GRANT` existía desde el principio.

### Por qué una columna y no solo el YAML

La opción 1 sola no alcanza: el YAML dice **con qué regla se cruza**, no **qué
se decidió**. El pedido tiene que guardar a quién se le pidió, y guardarlo de
forma que sobreviva a que alguien edite el YAML mañana. Con la clave escrita en
la fila, un pedido armado hoy sigue diciendo "LEVIC" aunque el mapa cambie; sin
ella, habría que deducirlo del `proveedor_id` y un pedido a QuePharma no tendría
de dónde deducirlo.

### Por qué no cambiar el tipo de `proveedor_id` a `text` (opción 4)

Era la opción más simple de escribir y la que más se pierde. El `pro_id` es **lo
único que conecta un pedido nuestro con lo que de verdad llegó**:
`marts.fct_compras` guarda `proveedor_id`, y la recepción sugerida —el
*probablemente recibido* del ADR 0002, ticket 26— va a cruzar por ahí. Tirarlo
para ahorrarse una columna dejaría ese cruce sin llave y habría que reconstruirlo
por nombre, que es justo lo que el punto anterior descarta.

## Consecuencias

- **Una compra a un proveedor sin puente no se va a poder cruzar sola con
  SICAR.** El pedido existe, se puede enviar (ticket 21) y se puede recibir a
  mano, pero el *probablemente recibido* del ticket 26 no lo va a alcanzar. La
  pantalla lo dice en el pedido, con esas palabras, en vez de dejarlo para que
  alguien lo descubra cuando la mercancía no se cierre sola.
- **El día que la farmacia le compre a QuePharma, SICAR le dará un `pro_id` y lo
  único que hay que hacer es agregar una línea al YAML.** Nada de código, nada
  de migración. Es el escenario para el que se eligió el YAML.
- **`config/continental.yml` pasa a llevar un dato que depende del catálogo de
  SICAR**, y eso es acoplamiento nuevo: si alguien borra y vuelve a crear un
  proveedor en SICAR, el id cambia y el YAML se queda apuntando a una fila que
  ya no está. Se ve como "sin nombre" en la pantalla y **no** como un pedido
  roto. **Condición de revisión:** si eso pasa más de una vez, el cruce deja de
  ser configuración y pasa a ser un dato que alguien mantiene desde la pantalla
  — y entonces sí es una tabla.
- **El ticket 21 paga una migración para ampliar `ck_pedido_estado`.** El CHECK
  conoce `borrador` y nada más. Se podría haber adelantado el valor de
  "enviado", como el ticket 12 adelantó el motivo `no empareja`; la diferencia
  es que aquel significado **ya estaba decidido** en el ADR 0002 y éste no:
  `CONTEXT.md` no tenía estados para el pedido, y fijar hoy cómo se llaman los
  del 21 sería decidir su glosario.
- **`borrador` entra al glosario.** `CONTEXT.md` define los estados del pedido
  sugerido y los del renglón, y no tenía ninguno para el pedido. Con él entra
  también la frase que evita el error obvio: **un renglón dentro de un pedido en
  borrador sigue `abierto`, no pasa a `en tránsito`** — el glosario define ese
  estado como "ya se le pidió a un proveedor", y un borrador no se le ha pedido
  a nadie.
- **`fk_renglon_pedido` se aprieta de paso**, y conviene decir que es un arreglo
  y no una mejora: con `(pedido_id, negocio)` un renglón de la lista del martes
  podía colgar de un pedido de la del lunes, la restricción se cumplía, y el
  total de ese pedido contaba mercancía de otro día. Ahora lleva
  `pedido_sugerido_id` y apunta a `ux_pedido_de_la_lista`.
- **Alguien tiene que leer `marts.dim_proveedor` algún día.** Hoy el puente vive
  entero en el YAML y **ningún código lee esa tabla todavía**, así que el
  `GRANT` sigue sin ejercitarse y un `dbt build` que se lo lleve por delante no
  se notaría hasta que la pantalla quiera escribir el nombre de SICAR al lado
  del pedido. El paso 2 del final de `sql/crear_rol.sql` —agregarle `grants` a
  `dim_proveedor.sql` en farmacia-data, que hoy no tiene ninguno— sigue
  pendiente y ahora importa más.
