# 0012 — Lo vendido mientras un renglón está en tránsito se queda en el almacén y vuelve al recibirse

**Fecha:** 2026-09-21  ·  **Estado:** aceptada

## Contexto

El ticket 24 es la memoria de lo ya pedido. El glosario ya decía qué quiere
decir `en tránsito` — *"ya se le pidió a un proveedor y todavía no llega. No se
vuelve a proponer mientras esté así, porque eso sería pedirlo dos veces"* — y
desde el ticket 21 el envío escribe ese estado. **Pero nada lo leía al armar la
lista**, y el doble pedido existía:

- **Sin ninguna venta nueva.** Una lista que se envió y **no se cerró** no
  mueve el corte (ticket 09): la siguiente arranca en el piso y vuelve a recoger
  sus mismos días. Lo que ya se le pidió a NADRO se propone otra vez, sumado en
  el mismo número por renglón, sin que nada lo delate.
- **Con venta nueva.** Pedido el lunes, llega el jueves: el martes y el
  miércoles el producto se sigue vendiendo con la existencia baja, y cada lista
  lo vuelve a proponer.

La primera casilla del ticket lo resuelve con una frase: el producto en
tránsito **no vuelve a proponerse**. La tercera casilla es la que cuesta:

> *Si el mismo producto se vuelve a vender mientras está en tránsito, esa venta
> no se pierde: queda contabilizada para cuando el renglón se cierre.*

Y se pierde con facilidad. La ventana del ticket 09 acumula **desde el corte del
último cerrado**: si el martes el producto se queda fuera por estar en camino y
la lista del martes se **cierra**, el corte avanza al martes y ninguna lista
posterior vuelve a mirar ese día. Las 2 piezas vendidas el martes desaparecen
para siempre, sin un solo error que ver — la falla que la regla 4 prohíbe.

Tres hechos delimitan la solución, y ninguno se decide aquí:

1. **Las ventas ya están guardadas.** `marts.fct_ventas` tiene cada línea con
   su fecha y Continental la lee cuando quiere; lo que el módulo guarda en
   `pedidos` son decisiones, no ventas.
2. **Las ventas llegan tarde.** El sábado llega el lunes en la noche (peor caso
   medido, 2.5 días). Cualquier foto de "lo vendido hasta hoy" envejece sola.
3. **La recepción todavía no existe.** Los tickets 26 y 27 ponen `recibido` y
   `recibido parcial`, y el 25 pone "cancelar". Lo que se decida aquí tiene que
   dejarles un enganche claro, no resolverlos.

## Opciones consideradas

1. **No excluir nada.** Seguir proponiendo el producto en tránsito y confiar en
   que el encargado lo descarte. Es el doble pedido de hoy.
2. **Excluir y olvidar.** Filtrar el producto de la lista mientras esté en
   tránsito, y nada más. Es la mitad obvia de la solución.
3. **Excluir y copiar lo retenido a una tabla** (`pedidos.venta_retenida`): al
   armar cada lista, escribir cuántas piezas del producto excluido se vendieron
   en esa ventana; al recibir, sumarlas.
4. **No dejar avanzar el corte** mientras haya algo en tránsito: la ventana
   entera de la lista se queda atrás hasta que llegue.
5. **Proponer y restar**: seguir proponiendo el producto, pero con la cantidad
   neta — vendido menos lo que ya viene en camino.
6. **Excluir y recordar el ancla**: la venta se queda en `marts.fct_ventas`, y lo
   que se recuerda es **hasta qué día de ventas repuso el renglón en tránsito**.
   Al cerrarse el renglón, la siguiente lista lee ese producto desde el día
   siguiente a esa ancla. *(elegida)*

## Decisión

**La sexta.** Tres piezas, las tres pequeñas:

- **El ancla ya existía.** Es la `ventas_consideradas_hasta` de la lista del
  renglón en tránsito, guardada desde el ticket 08. No se estrena tabla.
- **`lo_ya_pedido`** (una lectura nueva del almacenamiento, solo `SELECT`)
  devuelve, de listas anteriores al día: **todo** renglón `en tránsito`, y los
  `recibido` / `recibido parcial` **que ninguna lista posterior ha atendido**
  —atendido es: una lista posterior **cerrada** trajo el producto, o el producto
  se **volvió a pedir**—.
- **`transito.memoria_de_lo_pedido`** (pura) convierte eso en lo que
  `armar_la_lista` necesita: los productos en camino se quedan **fuera**; los
  que ya llegaron se cuentan **desde el día siguiente al ancla**, esté ese día
  antes de la ventana —trae lo que se vendió mientras venía— o después —la lista
  de aquel pedido no se cerró y esos días ya estaban pedidos—. La lectura de
  ventas se estira para que quepa y **sigue siendo una**.

El renglón que vuelve con una ventana propia lo dice en una columna nueva,
`renglon.ventas_desde` (migración 0008, sin tabla nueva), y en la pantalla con
una frase: *"Trae también lo vendido desde el martes 15 de septiembre, mientras
venía en camino: esas ventas no se perdieron."*

### Dónde queda la venta, cuándo vuelve, y qué les queda a 26 y 27

- **Dónde queda:** en `marts.fct_ventas`, donde ya estaba. No se copia a
  ninguna parte. Lo que se guarda es el ancla, y ya estaba guardada.
- **Cuándo vuelve:** en la **primera lista que se arme después de que el
  renglón pase a `recibido` o `recibido parcial`**. No al llegar la mercancía
  físicamente —Continental no lo sabe hasta que alguien lo dice— y no en la
  lista que ya estaba armada ese día: lo que se muestra es lo guardado.
- **El enganche:** `almacenamiento.ESTADOS_QUE_CIERRAN_EL_TRANSITO`, repetido
  con sus acentos en `_LO_YA_PEDIDO` y con una prueba que compara los dos.
  **Quien escriba `recibido` o `recibido parcial` no tiene que hacer nada más**
  para que lo retenido vuelva: el ticket 26 solo tiene que mover el estado. Hay
  pruebas que ya lo ejercitan poniendo `recibido` con el doble.

## Razones

### Por qué no la 1 (no excluir)

Porque el glosario ya lo había decidido y el ticket lo repite: proponer lo que
viene en camino es pedirlo dos veces. Y confiar en que el encargado lo descarte
es poner la garantía en la memoria de una persona que ve, con la reposición 1 a
1, un número que **no delata** el doble: las piezas del lunes y las del martes
salen sumadas en un solo renglón.

### Por qué no la 2 (excluir y olvidar)

Porque es exactamente la trampa de la tercera casilla. Con el ticket 09 la
ventana avanza con cada cierre, y un día que se cerró con el producto fuera ya
no lo vuelve a mirar nadie. La 2 cumple la casilla 1 rompiendo la 3, y lo hace
en silencio: el renglón que vuelve al recibirse trae solo lo de ese día, que
parece correcto.

### Por qué no la 3 (una tabla de ventas retenidas)

Suena a lo más explícito y es lo más frágil:

- **Copia un hecho que ya está guardado.** Dos copias de la misma venta se
  separan en cuanto una cambie, y la de `marts` cambia: dbt la reconstruye cada
  noche.
- **Envejece con las ventas que llegan tarde.** La foto se toma al armar la
  lista que excluye el producto; lo del sábado que llega el lunes no estaría en
  la foto del sábado. Releer desde el ancla lo recoge solo, la próxima vez que
  alguien arme una lista.
- **Una tabla nueva obliga a volver a correr `crear_rol.sql`**, que es el paso
  que más se olvida y el que peor avisa: con la 0004, el lote rebotaba con
  *permission denied* y la pantalla mentía a la mañana siguiente.
- Y tendría que decidir qué hacer con cada fila al recibirse, al cancelarse, al
  recibirse a medias. El ancla no necesita ninguna de esas reglas.

### Por qué no la 4 (congelar el corte)

Porque el corte es de **la lista entera** y el tránsito es de **un producto**.
Congelarlo por un renglón haría que la lista siguiente volviera a proponer
**todo lo demás** de esos días, que ya se pidió: el doble pedido que se quería
evitar, multiplicado por cada producto que no venía en camino.

### Por qué no la 5 (proponer y restar)

Porque rompe lo que hace defendible la reposición 1 a 1 (ADR 0002): "se
vendieron tres, se piden tres", aritmética que el encargado verifica de un
vistazo. "Se vendieron cinco, vienen tres, se piden dos" mezcla un hecho con una
promesa de un proveedor que quizá mande la mitad — que es el caso de todos los
días del ticket 27. Y el glosario ya dijo que el producto en tránsito **no** se
propone.

### Por qué el ancla es la ventana de la lista y no la hora del envío

Porque las ventas tienen grano de **día** (`fct_ventas` se une a `dim_fecha` y
no guarda hora) y la lista del renglón ya dice qué días repuso. Usar
`enviado_en::date` mezclaría un instante del reloj con fechas de venta —la
trampa del contenedor en UTC otra vez— y además dejaría fuera los días entre el
fin de la ventana y el envío, que la lista **no** propuso.

Lo que cuesta, dicho: las ventas del **mismo día del ancla** que lleguen tarde
—la tarde del viernes, que llega el lunes— se consideran cubiertas por ese
pedido. Es el mismo pedacito que ya pierde el corte de la lista (hilo abierto 6
de `HANDOVER.md`) y se resolvería igual: con hora en el almacén.

### Por qué un recibido se deja de recordar al atenderlo una lista **cerrada**

Porque así lo retenido se propone **una sola vez**. Si la lista que lo trajo de
vuelta se cierra, sus ventas ya se propusieron y el corte las cubre; recordar el
ancla más las propondría dos veces. Si esa lista **no** se cierra, nadie pidió
nada, y la siguiente las vuelve a traer — igual que el piso del ticket 09 hace
con los días de una lista vencida. Las dos memorias se comportan igual a
propósito.

### Por qué todo lo `en tránsito` se lee siempre, sin más condición

Porque se **enseña** (casilla 4) y porque saca el producto de la lista. Si un
tránsito se escondiera porque una lista posterior trae el mismo producto, ese
producto se propondría otra vez y además dejaría de verse que viene en camino.

## Consecuencias

- **`renglon.ventas_desde`**, `date` que admite nulos, con su migración `0008`
  y lo mismo en `crear_tablas.sql`. **No crea tabla**: `crear_rol.sql` no hace
  falta volver a correrlo. `verificar_rol.sql` gana la comprobación **30**. La
  migración va **antes** del código: las lecturas nombran la columna.
- **`armar_la_lista` exige la memoria**, sin valor por omisión: armar sin ella
  es volver a pedir lo que viene en camino, en silencio. La pantalla y el lote
  la leen **dentro** de `armar`, y si no se puede leer la lista no se arma —un
  hueco con su motivo, no una lista que pide dos veces guardada todo el día—.
- **La pantalla enseña lo que viene en camino** de listas anteriores, atenuado y
  con su frase —*"Pedido el martes a NADRO, sin recibir."*—, lo que se ha
  vendido de cada uno desde entonces, y la advertencia de la quinta casilla. Es
  la única lectura del almacén que la pantalla hace cuando la lista ya existía:
  de unos cuantos días, y solo si hay algo en camino.
- **El día de la semana se calcula en la zona de la farmacia**, UTC-6 fijo
  (México quitó el horario de verano en 2022; la torre no tiene `tzdata`). A
  partir de siete días el día de la semana ya no alcanza —"el martes" se lee
  como hoy— y va la fecha con cuántos días lleva, que es el número que el
  ticket 25 va a comparar contra su N.
- **Aquí el reloj sí se mira, y no contradice la regla del repo.** La regla es
  sobre **fechas de venta**. "Hace cuánto se envió" compara el instante del
  envío contra ahora; contra `max(fecha)` saldría mal, porque los lunes la
  última venta es del sábado. El reloj vive en `web/dependencias.reloj`, con
  los otros bordes: `app.py` sigue sin poder mirarlo.
- **Lo que NO protege, dicho en la pantalla:** un pedido capturado en un portal
  sin marcarlo aquí como enviado no está en tránsito, y su mercancía se va a
  proponer otra vez (ADR 0002 ya lo anotaba como consecuencia).
- **El borde que la memoria no alcanza, dicho en el renglón.** El ADR 0009
  permite enviar desde una lista vencida. Si eso pasa **después** de que la
  lista de hoy se armó con el mismo producto dentro, la de hoy ya no se
  recalcula; su renglón lo avisa (*"Ya viene en camino… pedirlo aquí también
  sería pedirlo dos veces"*) en vez de callar.
- **Lo que este ADR no decide.** Cancelar (ticket 25) **no** está en
  `ESTADOS_QUE_CIERRAN_EL_TRANSITO`, y es a propósito: un renglón que vuelve a
  `abierto` porque su pedido nunca se capturó no se recibió nunca, así que lo que
  tiene que volver es **también** lo que ese renglón repuso, no solo lo de
  después del ancla. Ese ticket decide si vuelve el renglón mismo o si la
  memoria lee desde el principio de su ventana. **Lo decidió el ADR 0013**: el
  renglón pasa a `cancelado` —no a `abierto`— y la memoria lee su producto
  desde el principio de lo que cubría, con esta misma sentencia. `recibido parcial` (ticket 27)
  trae de vuelta lo vendido después del ancla; **la diferencia de lo que no
  llegó** es regla de ese ticket y se suma aparte.
- **Condición de revisión.** Si un tránsito dura semanas (el ticket 25 lo
  señala como vencido), la lectura de ventas se estira hasta su ancla y la
  lista, al recibirlo, trae un renglón grande de golpe. Si eso resulta
  frecuente, la señal es que el tránsito vencido necesita resolverse antes, no
  que esta memoria esté mal.
