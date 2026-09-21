# 0006 — El lote nocturno corre después de la cadena, se detiene al tope, y su bitácora es el journal más la tabla que ya existe

**Fecha:** 2026-09-19  ·  **Estado:** aceptada

## Contexto

El ticket 18 pone a Continental a traer precios **solo, de noche**, para que en
la mañana la lista ya los tenga. Hasta hoy un precio llegaba porque alguien
apretaba un botón (ticket 12). Lo que hay que decidir antes de escribir la
unidad de systemd es **a qué hora corre, qué pasa cuando se le acaba el tiempo,
en qué orden consulta, y dónde queda escrito cómo le fue.**

Nueve hechos delimitan el problema, y ninguno es una suposición:

1. **La cadena de farmacia-data corre lun-vie 20:30** en atlas
   (`farmacia-diario.timer`; última corrida verificada, vie 18-sep 20:30). Es
   la que mete las ventas del día en `marts.fct_ventas`, que es con lo que la
   lista se arma.
2. **El respaldo de SICAR sube hacia las 18:51** de lunes a viernes, y su
   horario está **en propuesta** (ADR 0017 de farmacia-data, lo decide el
   dueño). Si se mueve a las ~20:15, la cadena se mueve a las 21:00.
3. **Una búsqueda en un portal tarde**: piso medido de ~9 s por proveedor,
   techo de 60-90 s. Cuatro proveedores por renglón.
4. **El tope de 60 minutos ya estaba decidido** —ADR 0002 y
   `config/continental.yml`— y el ticket lo repite: *lo que no alcanzó queda
   marcado sin precio, con su botón para completarlo*.
5. **`marts.dim_producto` NO tiene `clase_abc`.** El ADR 0018 de
   farmacia-data está **aceptado y sin implementar**: verificado el
   2026-09-19, la columna no aparece en un solo modelo de `dbt/models`. Sin
   ella, el orden de importancia que el ticket pide no se puede cumplir.
6. **Ese mismo ADR 0018 descartó a propósito el orden alterno**: su opción 2,
   "que Continental ordene por la utilidad de la ventana", está rechazada con
   su razón escrita —*"deja el orden de un módulo de compras dependiendo de la
   utilidad de siete días, que en un producto de rotación lenta es ruido"*—.
7. **Doyle todavía no está en atlas.** `~/proyectos/` tiene `borde`,
   `Farmacia`, `Marlowe` y `Sarabia` (medido el 2026-09-19 en solo lectura).
   El ADR 0008 de Doyle —el del navegador reutilizado por proveedor— está sin
   hacer, y hoy su `POST /api/buscar` arranca cuatro hilos por búsqueda.
8. **`pedidos.precio_de_proveedor` solo crece** (ADR 0004), se escribe en
   cuanto llega cada lectura, y su `motivo` es un vocabulario cerrado de ocho
   valores con su `CHECK`. Su propio ADR dejó una **condición de revisión**:
   *"si el lote nocturno hace que la tabla crezca un renglón por producto
   vendido por noche, con 3,429 artículos y cuatro proveedores serían ~13,700
   filas por corrida, y ahí el «solo crece» deja de ser gratis"*.
9. **`precios.py` ya tiene el motivo `no alcanzó el tiempo`** (`SIN_TIEMPO`),
   que la historia 31 pide distinguir de "el portal falló" con todas sus
   letras: uno se resuelve volviendo a consultar y el otro no.

## Opciones consideradas

**A qué hora corre**

1. Un `OnCalendar` fijo, con colchón medido contra la cadena.
2. `After=farmacia-diario.service` en la unidad del lote.
3. Un drop-in en `farmacia-diario.service` (`Wants=continental-lote.service`)
   para encadenarlas de verdad.

**Qué pasa con lo que no alcanzó**

A. Escribir cuatro filas de hueco con motivo `no alcanzó el tiempo` por cada
   renglón que no se consultó.
B. No escribir nada y contarlo en el resumen de la corrida.

**Dónde queda la bitácora**

α. El `journal` de systemd.
β. Una tabla nueva, `pedidos.corrida_del_lote`.
γ. Las dos.

**Cómo se ordena hoy, sin `clase_abc`**

I. Implementar el orden por utilidad de la ventana y marcar la casilla.
II. Dejar el orden como función pura, probada con dobles, y **no reordenar**
    mientras no haya clase — declarándolo en cada corrida.

## Decisión

**1 + B + γ (con matices) + II.**

- El timer es `OnCalendar=Mon-Fri 22:00`, noventa minutos después de la cadena,
  y el archivo lleva escrito que **si se mueve la cadena se mueve esto en el
  mismo movimiento**.
- Un renglón que no se alcanzó **no deja fila**: queda contado en el resumen
  con el motivo `no alcanzó el tiempo`, que es el que ya existía.
- La bitácora son **dos cosas con trabajos distintos**: el `journal` para el
  relato de la corrida, y `pedidos.precio_de_proveedor` —que ya existe— para
  el "por qué" de cada hueco. **No se estrena ninguna tabla.**
- El orden de importancia queda como función pura probada, y el lote **declara
  en cada corrida que no lo está cumpliendo** mientras la columna no exista.

## Razones

### La hora: un `OnCalendar` fijo, y por qué las otras dos no

**La 2 no hace nada y se lee como si sí.** `After=` solo ordena unidades que
arrancan en la **misma transacción** de systemd. Estas dos las disparan timers
distintos a horas distintas, así que escribirlo dejaría un archivo que parece
encadenado y no lo está — la peor clase de línea, porque quien la lea dejará de
preguntarse por la hora. Por eso la unidad lleva un comentario explicando que
**no** está ahí y por qué.

**La 3 es la respuesta correcta y no se puede hacer hoy**, por dos razones
separadas: el drop-in vive en `farmacia-diario.service`, que es de **otro
repo**, y este ticket no escribe en atlas (ahí corre Marlowe en producción). Se
deja anotada como lo que habría que hacer el día que las dos casas se puedan
tocar a la vez.

**El colchón son 90 minutos y no 15.** La cadena baja el respaldo de Drive con
rclone, restaura la réplica MySQL, ingesta a `raw`, hace el snapshot del día y
corre `dbt build` con sus 124 pruebas. Un lote que arrancara antes de que eso
termine armaría la lista con las ventas de **ayer** y les traería precios —sin
fallar y sin avisar, que es lo que este repo persigue—.

**Lun-vie**, igual que la cadena: el respaldo sube de lunes a viernes. Lo del
sábado y el viernes por la tarde llega hasta el lunes en la noche —peor caso
medido, 2.5 días— y el lote del lunes lo trae entero, porque el sugerido
acumula desde el último cierre y no desde "el último día" (ADR 0002).

**Sin `Persistent=true`**, y es una decisión: con él, un atlas apagado a las
22:00 dispararía el lote en cuanto arrancara —a las nueve de la mañana— y
serían cuatro navegadores contra los portales del dueño durante una hora, en
horario de mostrador, por una lista que el encargado ya tiene enfrente y cuyos
precios puede pedir con un botón. Una corrida perdida cuesta completar a mano;
una corrida a destiempo cuesta molestar cuatro portales ajenos cuando nadie lo
pidió.

**Y `TimeoutStartSec=75min`, que es la línea sin la cual el tope no existiría.**
`Type=oneshot` usa ese valor para matar el proceso y el de omisión de systemd
son 90 segundos: sin escribirlo, el lote consultaría un puñado de renglones, la
unidad quedaría en `failed` cada noche, y el journal diría "timeout" en vez de
decir que se consultaron nueve de trescientos. Setenta y cinco y no sesenta
porque el tope se mira **antes** de arrancar cada renglón y no en medio de uno:
el lote se puede pasar por lo que tarde el que estaba en curso, y eso está
acotado en 120 s por el tope por consulta.

### Lo que no se alcanzó no deja fila

La opción A es la tentadora —"que se vea en la pantalla"— y tiene dos costos
que juntos la hunden:

- **Habría que inventarse a qué proveedores se le iba a preguntar.** Esa lista
  sale del acuse de Doyle, y a un renglón que no se consultó no hubo acuse que
  darle. Es exactamente el hilo abierto 3 de `HANDOVER.md`, donde ya se decidió
  no resolverlo a medias: *"se arreglaría escribiendo cuatro filas con motivo
  contra una lista fija de proveedores, y eso es inventarse de dónde sale esa
  lista"*.
- **Dispararía la condición de revisión del ADR 0004.** Una noche en la que el
  tope corte al 20% dejaría ~11,000 filas de puro hueco, cada una diciendo algo
  que no pasó.

Lo que sí se conserva es la información: el resumen cuenta cuántos quedaron
faltantes por tope, y la pantalla ya sabe decir "nadie los consultó" (ticket
15). Lo que queda **sin cerrar** es distinguir en la pantalla "nadie los
consultó porque el lote no llegó" de "nadie los consultó porque el lote no
corrió"; hoy eso solo se ve en el journal. **Condición de disparo:** si el
encargado pregunta dos mañanas seguidas por qué media lista no tiene precio,
eso deja de ser un detalle y el lugar natural es la tabla de bitácora de la
opción β.

**Y el motivo es `no alcanzó el tiempo` y no uno nuevo.** Es literalmente lo
que pasó, la historia 31 ya lo pedía separado de "el portal falló", y los dos
casos se arreglan igual: volviendo a consultar. Un motivo que se atiende como
otro sobra, y el vocabulario cerrado cuesta una migración y un `CHECK` cada vez
que crece.

### La bitácora: el journal, más la tabla que ya existe

**El `journal` para el relato.** Es donde esta casa ya mira "cómo le fue
anoche": farmacia-data lo hace con `journalctl -u farmacia-diario`. Cuesta cero,
no necesita migración, y —lo que de verdad importa— **un lote que truena antes
de poder escribir en Postgres deja rastro ahí igual**. El resumen se escribe en
un `finally`, así que sale hasta cuando alguien mata el proceso.

**La tabla que ya existe para el "por qué".** `pedidos.precio_de_proveedor`
guarda un motivo por hueco, con vocabulario cerrado y `CHECK`: *"cuántos
quedaron sin precio y por qué"* es un `group by motivo` sobre filas que ya se
están escribiendo. Copiar esos conteos a una tabla de bitácora crearía **dos
versiones de la misma noche** que pueden dejar de coincidir, que es el mismo
problema que el ADR 0018 describe con sus cinco copias de la clase ABC.

**Lo que la opción β sí compraría, dicho para no fingir que no existe:** poder
preguntar *"¿corrió el lote anoche?"* con SQL, desde la pantalla, sin ssh. Hoy
eso solo se contesta con `journalctl`. No se construye ahora porque una tabla
nueva cuesta una migración, volver a correr `crear_rol.sql` —un GRANT no se
puede dar sobre una tabla que no existía—, tocar `verificar_rol.sql` y
`continental.verificar`, y todo eso para un dato que nadie ha pedido todavía.
**Condición de disparo:** cuando la pantalla tenga que decir "el lote de anoche
consultó 210 de 380", eso es la tabla y no un `journalctl` parseado.

### El orden: función pura hoy, lectura el día que exista la columna

La opción I —implementar el orden por utilidad y marcar la casilla— **está
descartada por el ADR 0018 mismo**, que la consideró y la rechazó. Hacerla aquí
sería reabrir un ADR de otro repo por la puerta de atrás, y además marcaría como
cumplida una casilla que dice, con esas palabras, *"leyendo la clase ABC del
catálogo"*.

Así que el orden se construyó **entero**: `lote.ordenar_por_importancia` recibe
los renglones y su clase y devuelve el orden A-B-C con la urgencia como
desempate estable, probado con dobles que sí traen clase. Lo que no se puede
hoy es **leerla**, y eso se resuelve en tres lugares que se mueven solos:

- `almacen.Producto.clase_abc` existe y vale `SIN_CLASE_ABC` en las 3,429 filas.
- `almacen.LA_CLASE_ABC_ESTA_EN_DIM_PRODUCTO` es el único interruptor. La
  consulta de hoy **ni siquiera nombra la columna**: un `select clase_abc`
  rebotaría con "column does not exist" y se llevaría por delante la lista del
  día entera, porque el catálogo es una de las dos lecturas con las que se arma.
- `verificar.revisar_clase_abc` lo imprime como `PENDIENTE` en cada despliegue,
  con el nombre de esa constante dentro. Es el mismo trato que el ticket 17 le
  dio al invariante 3, y por la misma razón: quien implemente el ADR 0018 no
  tiene por qué acordarse de volver aquí.

Y **mientras tanto el lote no reordena nada**: consulta en el orden de urgencia
con el que la lista se armó y se guardó, que es además el que el encargado ve en
la pantalla. No reordenar es lo único honesto cuando el criterio no está;
cualquier otro orden sería inventado.

### Lo que este ADR NO decide, porque no es de aquí

**El navegador reutilizado por proveedor es de Doyle** (su ADR 0008).
Continental no abre un navegador nunca (regla 1 de `CLAUDE.md`), así que esa
casilla del ticket 18 **no se puede cerrar en este repo**. Lo único que de este
lado depende es no pedirle a Doyle cuatro búsquedas a la vez, y no se le piden:
el lote es **estrictamente secuencial**, un renglón tras otro, esperando a que
cada uno termine. Un lote concurrente sería justo lo que le impediría a Doyle
reutilizar lo que tenga abierto. La cortesía entre productos tampoco se aplica
aquí: la pone Doyle dentro de su búsqueda (3 s medidos), y repetirla gastaría
del tope de 60 minutos sin que ningún portal lo notara.

## Consecuencias

- **El lote consulta también los renglones que ya tienen precio de esa tarde.**
  No se saltan, y es a propósito: decidir "qué tan viejo es viejo" es una regla
  que nadie ha tomado, y la tabla solo crece, así que volver a consultar no
  pierde nada —solo gasta tope—. **Condición de disparo:** si el lote se queda
  sin tiempo de forma habitual, lo primero que hay que probar es saltarse lo
  que ya tenga lectura de esta misma noche, antes de subir el tope.
- **El lote consulta también los renglones de abarrote**, y eso gasta tope en
  productos que no se le compran a estos cuatro proveedores (`CONTEXT.md`:
  el abarrote *"compite contra la tienda de la esquina, no contra una
  farmacia"*). No se filtran por la misma razón por la que la pantalla tampoco
  lo hace: **nada se filtra** (ADR 0002), y el filtro que habría que escribir
  no es limpio — hay 688 de 3,429 artículos **sin anaquel conocido**, que caen
  en `sin clasificar` y no en `abarrote`, así que saltarse "lo que no es
  medicamento" dejaría sin precio a un montón de mercancía que sí se compra.
  Saltarse solo lo que es `abarrote` con todas sus letras sí sería seguro, y es
  lo que hay que hacer si el tope aprieta. **Condición de disparo:** si el lote
  no termina la lista en 60 minutos, esto se mide primero —cuántos renglones de
  la lista son `abarrote`— antes de tocar el tope.
- **Una corrida que se detiene al tope sale con código cero.** Detenerse a los
  60 minutos es lo que se le pidió; marcarlo en rojo cada noche haría que nadie
  volviera a mirar el journal, que es donde vive la bitácora. Lo que sí sale
  distinto de cero es una corrida cortada.
- **El lote no reintenta.** No hay `Restart=` en la unidad: lo consultado ya
  está guardado, y volver a empezar molestaría otra vez a los cuatro portales
  del dueño por renglones que ya tienen precio. Lo que quedó se completa con el
  botón de la pantalla.
- **El lote abre la lista del día**, cosa que hasta hoy solo hacía la pantalla.
  Para que las dos no se separen, "las dos lecturas y el cálculo" viven ahora en
  una sola función, `sugerido.armar_la_lista`, y `web/app.py::_armar` delega en
  ella. Es la única función de `sugerido.py` que toca un borde, y va anunciada
  en su encabezado.
- **Se cierra el hilo abierto 2 de `HANDOVER.md` en su condición de disparo**:
  el lote consulta la lista entera de golpe, así que el conteo de huecos ya no
  envejece por su culpa. Lo que queda abierto sigue siendo la ruta de un
  renglón suelto.
- **El hilo abierto 3 cambia de color.** Un fallo de Doyle al pedir la búsqueda
  sigue sin dejar fila, pero ahora sí deja rastro: el resumen del lote dice
  cuántos renglones quedaron `no se pudo` y con qué tipo de falla. Lo que sigue
  sin poderse contestar con SQL es "¿corrió el lote anoche?".
- **El hilo abierto 5 gana un consumidor más.** Mover el respaldo de SICAR ya
  obligaba a mover la cadena; ahora obliga a mover **tres** cosas: el respaldo,
  `farmacia-diario.timer` y `continental-lote.timer`. Está escrito dentro del
  propio archivo del timer, que es donde lo va a leer quien lo esté editando.
- **Condición de revisión:** si con `clase_abc` puesta el lote sigue sin
  terminar la lista en 60 minutos, el problema no es el orden sino el número —o
  cuánto tarda Doyle— y ahí hay que medir cuántos renglones por hora consigue de
  verdad antes de tocar el tope. Ese número no se puede estimar hoy: las cuatro
  sesiones de Doyle están caducadas y no hay una sola lectura real contra un
  portal.

## Enmienda del 2026-09-21 — qué quiere decir "orden cumplido"

**Decidido por el dueño el 2026-09-21.** La columna ya existe
(`marts.dim_producto.clase_abc`, farmacia-data `c989ecb`, ADR 0018 de allá) y
Continental la lee desde `f3d7120`, así que el hecho 5 y la opción II de arriba
describen el estado al 2026-09-19. Lo que quedaba por decidir era la regla de
`Orden.cumple_el_orden`, que hasta hoy era falsa **si un solo renglón** no
tenía clase.

Esa regla chocaba con el propio ADR 0018: `clase_abc` es NULL **a propósito**
en lo que no vendió en 365 días —el 55% del catálogo—, así que el lote habría
declarado "SIN CUMPLIR" casi cada noche aunque el orden aplicado fuera
exactamente el que ese ADR describe: A, B, C y al final lo que no se sabe. Una
alarma que suena siempre enseña a no mirarla.

**La regla nueva:** el orden **no se cumple solo cuando la lista tiene
renglones y ninguno trae clase** (el catálogo no la trajo, o ninguno de la
lista la tiene); ahí el lote consulta en el orden de urgencia y lo declara como
antes. Si **algunos** no la traen, el orden se cumple y cuántos quedaron sin
clase va a la bitácora **como dato, no como falla**. Una lista vacía cumple:
no hay nada fuera de orden, y la bitácora dice "no hay nada que ordenar".

La regla vive en un solo lugar, `lote.ordenar_por_importancia`. La fila de
`pedidos.corrida_del_lote` (`orden_cumplido`, ADR 0007, sin cambio de esquema)
y el aviso de la pantalla (`faltantes.frase_de_la_corrida`) la copian y la
leen; el latido de Kuma no depende de ella. Una corrida que nunca llegó a
calcular el orden —sin lista, o cortada antes— sigue guardando `orden_cumplido`
en falso. **Condición de revisión:** si la bitácora muestra que en una lista
real la mayoría de los renglones sale sin clase, "cumplido" deja de decir mucho
y hay que volver a mirar la regla.
