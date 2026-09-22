# 0015 — Lo que faltó vuelve como piezas, lo recibido se dice en total, y el estado del pedido se calcula

**Fecha:** 2026-09-21  ·  **Estado:** aceptada

## Contexto

Hasta el ticket 26 un renglón en tránsito salía de ahí de una sola manera: una
compra de SICAR que trajera **al menos** lo pedido, confirmada por una persona
(ADR 0014). Tres casos de todos los días no tenían salida:

1. **El proveedor manda la mitad.** La propuesta decía *"es un recibido
   parcial, que todavía no se puede marcar aquí"*, y el renglón se quedaba en
   tránsito hasta verse atrasado.
2. **Lo que nunca deja compra en SICAR**: un pedido a QuePharma (sin puente,
   ADR 0008) y el 17.7% del catálogo que nunca aparece en compras. La pantalla
   decía que su única salida —el recibido a mano— *"todavía no existe"*.
3. **Un pedido que llega en dos facturas.** SICAR no tiene estado parcial
   (`compra.status` solo vale 1 o -1): la primera factura trae 6 de 10, la
   segunda el jueves trae el resto.

El glosario ya decía qué es `recibido parcial` —*"llegó menos de lo pedido. Lo
que faltó vuelve a proponerse"*— y el ticket 27 pide cinco cosas: indicar
cuántas llegaron, que la diferencia vuelva, marcar a mano, que el **pedido**
quede `recibido` o `recibido parcial`, y que todo lo manual vaya firmado.

Cinco preguntas no estaban contestadas en ninguna parte, y este ADR las
contesta:

- **Cómo vuelve "la diferencia"** sin chocar con la memoria de los tickets 24
  y 25, que ya hacen volver cosas por fecha.
- **El estado del pedido**: ¿se guarda o se calcula?
- **Dos facturas y cifras mal capturadas**: ¿se puede cambiar lo recibido?
- **Cancelar después de un recibido parcial**: ¿sigue prohibido?
- **Una propuesta del 26 que trae de menos**: ¿qué salida tiene?

Tres hechos delimitan la solución:

- **La memoria del 24 ya devuelve algo al recibir**: lo vendido *mientras
  venía*, desde el día siguiente al ancla (ADR 0012). `recibido parcial` ya
  está en `ESTADOS_QUE_CIERRAN_EL_TRANSITO`, así que eso vuelve solo.
- **La del 25 devuelve otra cosa al cancelar**: el producto desde el principio
  de lo que el renglón cubría (ADR 0013).
- **El 26 dejó la puerta abierta**: `ck_renglon_recepcion` pide firma para
  `recibido parcial`, y `recibido_con_compras` admite `NULL` en lo recibido.

## Opciones consideradas

**Cómo vuelve lo que faltó** (pedí 10, llegaron 6, faltan 4):

A. **Por fecha, como lo cancelado**: el parcial devuelve su producto desde el
   principio de lo que cubría.
B. **No vuelve nada aparte**: que la persona corrija la cantidad a mano en la
   siguiente lista.
C. **Por piezas**: el renglón guarda cuántas llegaron; la memoria recuerda
   `pedido − llegaron` y la siguiente lista **suma esas piezas** a lo vendido.
   *(elegida)*

**El estado del pedido:**

i. **Guardado**: `ck_pedido_estado` gana `recibido` y `recibido parcial`, y
   cada sentencia que mueve un renglón actualiza también su pedido.
ii. **Calculado** de sus renglones cada vez que se mira. *(elegida)*

**Recibir a mano y corregir:**

a. **Sumar**: cada factura se captura aparte ("llegaron 4 más").
b. **Total**: se escribe cuántas llegaron **en total**; recibir y corregir son
   la misma pregunta. *(elegida)*
c. **Final**: un `recibido parcial` no se toca más.

## Decisión

**C + ii + b**, y las otras dos preguntas con una frase cada una.

### 1. Lo que faltó vuelve como piezas, aparte de lo vendido mientras venía

- `renglon.piezas_recibidas` (`numeric(12,3)`) guarda cuántas llegaron. De ahí
  sale el estado, y la tabla lo amarra: `ck_renglon_completo_o_parcial` exige
  `recibido` ⇔ `piezas_recibidas >= coalesce(cantidad_final, cantidad_propuesta)`.
- `RenglonGuardado.lo_que_falto` es lo pedido menos lo recibido, hacia arriba.
- `LoYaPedido.piezas_que_vuelven`: el parcial devuelve lo que faltó; **el
  cancelado devuelve lo que faltó que traía** (vuelve "con todo lo que
  cubría", ADR 0013); el completo, cero.
- `MemoriaDeLoPedido.faltaron` es un tercer mapa —de piezas, no de fechas—
  que sale **del mismo renglón** que decide `desde`, y se olvida con la misma
  regla (`_LO_YA_PEDIDO` no cambia).
- `calcular_pedido_sugerido(..., faltaron=)` las **suma** a lo vendido, y un
  producto que faltó entra a la lista aunque no se haya vuelto a vender.
  `renglon.piezas_que_faltaron` guarda cuántas trae, para que la suma se vea.

### 2. El estado del pedido se calcula

`recepcion.estado_del_pedido(pedido, renglones)` devuelve los cinco estados del
glosario: `borrador` y `cancelado` como se guardaron; `enviado` mientras algo
venga en camino —o si nada llegó—; `recibido` si todos llegaron completos;
`recibido parcial` si alguno llegó de menos **o se dejó de esperar**. La
pantalla lo enseña (`estado_a_la_vista`, con su frase) y `pedido.estado` sigue
diciendo lo guardado. **La 0011 no toca `pedidos.pedido`.**

### 3. Lo que se escribe es el total, y se corrige mientras nadie lo haya atendido

`POST /api/renglon/{id}/recepcion/a-mano {"piezas": N}`: en tránsito →
`recibido` o `recibido parcial` (`_RECIBIR_A_MANO`); ya recibido → la cifra se
corrige (`_CORREGIR_LO_RECIBIDO`), también lo confirmado con compras, **salvo**
que una lista posterior ya haya atendido el producto (cerrada con él dentro, o
el producto vuelto a pedir): el mismo "atendido" de `_LO_YA_PEDIDO`. Las piezas
se validan en el servidor (`recepcion.piezas_escritas`): entero, de 1 en
adelante. **Más de lo pedido se acepta** como `recibido`, y lo que sobra no se
descuenta de ninguna lista. Firma: la de quien dijo la cifra guardada.

### 4. Cancelar después de un parcial sigue prohibido

`_CANCELAR_EL_PEDIDO` ya tenía `recibido parcial` en su `NOT EXISTS`: si algo
llegó, se capturó. Lo que sigue en camino de ese pedido se recibe a mano o se
devuelve cuando se atrase (ADR 0013). No cambió una línea.

### 5. La propuesta que trae de menos se recibe parcial con su evidencia

`POST /api/renglon/{id}/recepcion/parcial {"compras": [...]}`: la misma ida y
vuelta que confirmar —el servidor recalcula la propuesta y contesta 409 si ya no
es la que se vio— y la misma tabla con la cantidad al revés
(`_RECIBIR_PARCIAL_CON_COMPRAS`: `pedido > :piezas > 0`). La compra queda en
`recibido_con_compras`, y una compra sigue sosteniendo un solo renglón.

## Razones

### Por qué piezas y no fechas (y por qué no se rompe la regla del ADR 0002)

Lo que faltó **no son las ventas de ningún día en particular**: el renglón de
10 cubría las ventas de su ventana, llegaron 6, y no hay manera de saber
*cuáles* de esas 10 ventas quedaron sin reponer. Solo se sabe cuántas.

- **La A propone dos veces.** Volver a leer la ventana original trae las 10
  ventas; 6 ya se repusieron con lo que llegó. Habría que restar, y restar es
  exactamente lo que la opción 5 del ADR 0012 descartó.
- **La B pierde piezas en silencio.** La siguiente lista traería solo lo
  vendido mientras venía; las 4 dependerían de que alguien se acuerde —la
  falla que la regla 4 prohíbe—.
- **La C suma dos cosas que no se tocan.** Lo vendido mientras venía vuelve por
  el ancla (desde el día siguiente a la ventana original, ADR 0012); lo que
  faltó son ventas **de** esa ventana. Son conjuntos de ventas disjuntos: uno
  empieza donde el otro termina. Ninguna venta se cuenta dos veces.

**¿Rompe la reposición 1 a 1?** No, y conviene decirlo con cuidado: la regla
es *"se vendieron tres, se piden tres"*. Las 4 piezas **se vendieron** —en la
ventana del pedido que llegó de menos— y **no se repusieron**; sumarlas es
reponer lo vendido, no una promesa ni un mínimo. Lo que sí cambia es la
aritmética que el encargado verifica: ya no es "vendidas = propuesta", sino
"vendidas + las que faltaron = propuesta". Por eso el renglón guarda las dos
cifras (`piezas_vendidas` y `piezas_que_faltaron`) y la pantalla lo dice:
*"Trae también 4 piezas que faltaron en un pedido anterior"*. El redondeo va
hacia arriba, igual que `_piezas_a_pedir`: una evidencia de granel de 2.5 de 5
deja 3.

### Los números, de varios días (`tests/test_parcial.py`)

- **Pedí 10, llegaron 6.** Lunes se venden 10 y se piden 10. Martes 3,
  miércoles 2 (las dos listas se cierran sin el producto). Jueves llegan 6, se
  reciben a mano, y se vende 1. La lista del jueves propone **3 + 2 + 1 = 6**
  vendidas mientras venía **+ 4** que faltaron = **10**. Se cierra. Viernes se
  vende 1: propone **1**. Vendidas 17; repuesto 6 + 10 + 1 = 17.
- **Dos facturas.** Lunes 10, llegan 6. La lista del martes (que nadie cierra)
  trae 3 + 4 = 7. El miércoles llega el resto y se corrige a 10: la del
  miércoles trae 3 + 2 = **5**, ninguna de las 4.
- **Cancelado que traía lo que faltó.** Lunes 10, llegan 6. La del martes trae
  3 + 4 = 7, se envía… y el pedido se cancela. La del miércoles trae 3 + 2
  vendidas + 4 = **9**. Vendidas 15, llegaron 6: faltan 9.
- **Evidencia que trae de menos.** Pedido de 5, compra de 3, "llegaron solo
  3". El jueves: 1 + 1 vendidas mientras venía + 2 = **4**.

### Por qué el estado del pedido no se guarda

- **Es un hecho derivado.** Sale entero del estado de sus renglones, que ya
  están guardados y firmados. Guardarlo es una segunda copia, y se separa en
  cuanto un camino mueva un renglón sin acordarse del pedido: recibir con
  compras, recibir parcial, recibir a mano, corregir la cifra, devolver un
  atrasado. Cinco sentencias, y un olvido no daría ningún error.
- **Un cuarto estado guardado rompe cuatro `WHERE`.** `_CONFIRMAR_LA_RECEPCION`,
  `_RECHAZAR_LA_RECEPCION`, `_DEVOLVER_EL_ATRASADO` y `_RECIBIR_A_MANO` exigen
  `p.estado = 'enviado'`. Un pedido guardado como `recibido parcial` con otro
  renglón todavía en camino ya no dejaría recibir ese renglón. El ticket 25
  midió lo mismo en la pantalla: un tercer estado rompió `!fue_enviado`.
- **`enviado` sigue siendo verdad.** Alguien lo capturó en el portal (ADR
  0009); que después llegara no lo desmiente. `fue_enviado`, `es_borrador` y
  `fue_cancelado` siguen significando lo mismo, y la pantalla toma la etiqueta
  de `estado_a_la_vista`.

Lo que cuesta, dicho: el estado del pedido **no se puede consultar con un
`WHERE estado = 'recibido'`** sobre `pedidos.pedido`. Si algún día hace falta
—un reporte de pedidos incompletos—, es un `GROUP BY` sobre sus renglones, y se
escribe entonces.

### Por qué el total y no sumar

"¿Cuántas llegaron?" es la pregunta que el encargado sabe contestar con la
factura en la mano, y la misma sirve para recibir, completar con la segunda
factura y arreglar una cifra mal tecleada. Sumar (a) no deja corregir un error
—solo agregarle— y guarda una historia de sumas que nadie consulta. Congelar
(c) deja la segunda factura sin salida: las 4 que llegaron el jueves se
volverían a pedir.

**Por qué no se corrige lo ya atendido.** Si una lista posterior **cerrada** ya
propuso las 4 —y quizá se pidieron—, cambiar la cifra ya no cambia nada que se
vaya a pedir y diría lo contrario. Una lista posterior **abierta** no lo
impide: nadie ha pedido nada. Pero lo que se muestra es lo guardado y no se
recalcula (ADR 0012), así que el renglón de esa lista **lo avisa**: *"Las 4
piezas que faltaron y este renglón trae ya no faltan… corrige esta cantidad"*.
Es el mismo borde que *"ya viene en camino"* del ticket 24, y lo cazó el
recorrido del navegador.

**Por qué la firma se mueve.** `recibido_por` es quien dijo la cifra que está
guardada, que es a quien se le pregunta cuando no cuadre. La de antes queda en
la bitácora. Guardar todas pedía una tabla y volver a correr `crear_rol.sql`,
el mismo costo que el ADR 0014 no pagó por el rechazo.

**Por qué más de lo pedido se acepta.** Puede ser una bonificación u otro
pedido del mismo producto. Rechazarlo obligaría a escribir una cifra falsa; y
descontar el sobrante de la siguiente lista es "proponer y restar", la opción
5 del ADR 0012. Hay un tope (`PIEZAS_RECIBIDAS_MAXIMAS`, 99,999) que no es
regla del negocio: es lo que se cree sin preguntar.

### Por qué la puerta del 26 ya bastaba para cancelar

`_CANCELAR_EL_PEDIDO` nació con `r.estado in ('recibido', 'recibido parcial')`
en su `NOT EXISTS` (ticket 25) y el 26 lo ejercitó con `recibido`. Con el
parcial pasa lo mismo: llegó algo, luego sí se capturó. La prueba nueva lo fija.

## Consecuencias

- **Migración 0011** (`sql/migraciones/0011-recibido-parcial-y-a-mano.sql`) y
  lo mismo en `sql/crear_tablas.sql`: dos columnas en `renglon`
  (`piezas_recibidas`, `piezas_que_faltaron`) y tres CHECK
  (`ck_renglon_piezas_recibidas`, `ck_renglon_completo_o_parcial`,
  `ck_renglon_piezas_que_faltaron`). Rellena lo confirmado por el 26 con lo
  pedido **antes** de poner los CHECK, y se detiene con su motivo si encuentra
  un parcial sin cifra. **No crea tabla y no toca `pedidos.pedido`**:
  `crear_rol.sql` **no** se vuelve a correr. `verificar_rol.sql` gana las
  comprobaciones 36 y 37. **Va antes de desplegar**: las lecturas de renglones
  nombran las columnas y `_INSERTAR_RENGLONES` escribe una.
- **Dos rutas**: `/recepcion/a-mano` y `/recepcion/parcial`. Las dos firman con
  el correo de Access —firma y nunca permiso—, y los errores viajan como tipo.
- **La pantalla**: cada renglón en camino tiene su "Recibir a mano"; la
  propuesta que trae de menos, su "Llegaron solo 3 de 5: recibir parcial"; lo
  recibido de hoy y lo que llegó de menos de listas anteriores, su "Corregir
  cuántas llegaron"; el pedido, su estado calculado con frase.
- **El hilo abierto 18 se cerró de paso**: la partición con algo enviado y algo
  sin proveedor ya no dice "se pidió entera… en tránsito" (con lo recibido del
  27 habría mentido dos veces).
- **Lo que no protege**: un producto cuyo pedido se envió desde una lista vieja
  **después** de armar la de hoy (el borde del ADR 0012) sigue sin recalcular;
  y un parcial "atendido" por una lista que se armó con el producto dentro
  **antes** de marcar el parcial perdería lo que faltó —el mismo borde, con la
  misma salida: la persona lo ve en la pantalla—.
- **Condición de revisión.** Con un mes de recepciones, medir cuántos parciales
  se corrigen después (segunda factura) y cuántos llegan a una lista cerrada
  con lo que faltó. Si la segunda factura llega casi siempre después de que se
  cerró la lista, el candado de "atendido" está demasiado apretado y conviene
  una acción "ya no falta" sobre el renglón de la lista.

## Enmienda 2026-09-21 — el motivo real vive en `transiciones.py`, no en `app.py`

**El caso que encontró la revisión de arquitectura (propuesta 1), sobre el
código ya aceptado arriba.** La bandera `se_puede_corregir` que la pantalla
usa para pintar el botón era, desde que este ADR se escribió,
`renglon.esta_recibido` a secas (`app.py` ~línea 3832): no miraba que el
pedido siguiera `enviado`, ni el "atendido" del punto 3 de la decisión. La
pantalla ofrecía "Corregir" en casos que el `WHERE` de
`_CORREGIR_LO_RECIBIDO` iba a rechazar con un 409, y ese 409 a su vez
**adivinaba** el motivo con `antes.esta_recibido` y un texto genérico que
mentía cuando la razón real era "no viene en camino" (recibir a mano sobre un
renglón que nunca se envió) en vez de "ya lo atendió una lista posterior" o
"la cifra ya es ésa".

**Decisión:** la regla de este punto de la decisión —"salvo que una lista
posterior ya haya atendido el producto"— se escribe **una sola vez**, en
`continental.transiciones.motivo_para_no_corregir`, función pura sin I/O.
Tres consumidores la comparten: la bandera `se_puede_corregir` del JSON de la
lista, el 409 de `POST /api/renglon/{id}/recepcion/a-mano` (que antes
adivinaba) y —en pasos futuros de la misma propuesta— el doble. El **candado
real sigue siendo el `WHERE`**; `transiciones.py` es la copia legible y
probada, igual que `cierre.motivo_para_no_reabrir` ya lo es para reabrir.

La lectura que le falta al renglón —si una lista posterior ya lo atendió—
también se escribe una sola vez: `almacenamiento.productos_atendidos_despues
(negocio, pedido_sugerido_id)` devuelve el conjunto de `producto_id` de una
lista que una lista posterior ya atendió, con el mismo texto SQL
(`_ATENDIDO_POR_UNA_LISTA_POSTERIOR`) que ahora usa también
`_CORREGIR_LO_RECIBIDO` —extraído de su `NOT EXISTS` para que las dos no
puedan divergir—. La pantalla la pregunta **una vez por respuesta**, no una
vez por renglón recibido (la misma economía que ya tenía `_la_reapertura`
para el botón de reabrir).

**Qué NO se movió, a propósito.** Los demás motivos —cancelar, reabrir,
enviar— siguen en `transito.py`, `cierre.py` y `particion.py`. Moverlos
todos de un golpe habría mezclado el arreglo de un error visible con una
reorganización mucho más grande, que no se puede revisar por separado si
llega junta. Queda para un ticket aparte.
