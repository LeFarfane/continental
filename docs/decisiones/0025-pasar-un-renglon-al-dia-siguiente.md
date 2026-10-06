# 0025 — Un renglón se puede pasar al día siguiente

**Fecha:** 2026-10-05  ·  **Estado:** aceptada

**Enmienda el ADR 0020** en un solo punto: lo no pedido sigue sin arrastrarse
solo, pero una persona puede mandar un renglón, a propósito, a la lista
siguiente.

## Contexto

El ADR 0020 decidió que lo que queda sin pedir **no pasa** a la lista del día
siguiente: la de ayer se cierra sola y lo que no se pidió se da por atendido.
Descartó arrastrarlo porque, sin nadie que descarte, la sección arrastrada
crece hasta volver a los 174 renglones de septiembre. Y dejó escrita su
condición de revisión: *si la encargada empieza a pedir desde la lista, la
opción 2 vuelve a la mesa*.

Esa condición se cumplió a medias el 2026-10-05, y de un modo más preciso que
"arrastrar todo". El dueño a veces le pone un **tope de dinero** al pedido del
día. La encargada arma la lista, se la enseña, y si se pasa hay que recortar:
algunos artículos **sí se necesitan, pero mañana**. Hoy solo tiene dos salidas
y las dos mienten:

- **Descartar** dice "una persona decidió no pedirlo". Al día siguiente el
  producto no vuelve, y lo que se vendió se pierde de la reposición.
- **Dejarlo abierto** lo pierde igual: la lista se cierra sola esta noche y lo
  no pedido se da por atendido (ADR 0020).

## Decisión

**Cada renglón de la lista de hoy tiene un botón para pasarlo al día
siguiente.** Va junto a la cruz de descartar, en la fila y en el detalle.

1. **Es un estado nuevo del renglón, `pospuesto`**, con firma —quién y
   cuándo—, igual que `descartado`. No es un descarte con una bandera: los dos
   salen de la lista de trabajo, pero dicen cosas opuestas ("no se pide" contra
   "se pide mañana"), y el día que alguien cuente descartes no puede contar
   también los recortes por tope.
2. **Solo desde una lista que se puede editar, y solo un renglón `abierto`.**
   La misma regla que descartar (`transiciones.motivo_para_no_editar`). Un
   renglón ya pedido, en tránsito o recibido no se pospone.
3. **Se deshace igual que un descarte**, mientras la lista se pueda editar: el
   renglón baja a su propio bloque, "pasan al día siguiente", con su botón
   para devolverlo. Un clic y sin diálogo, por la misma razón del ADR 0002:
   lo que lo hace seguro es que se puede deshacer.
4. **Lo que pasa son piezas, no ventas**: la cantidad que el renglón iba a
   pedir —la ajustada si alguien la cambió, la propuesta si no
   (`cantidad_a_pedir`)—. Se **suma** a lo vendido del producto en la lista
   siguiente, con el mismo mecanismo que `piezas_que_faltaron` (ticket 27, ADR
   0015), y se guarda aparte en el renglón nuevo (`piezas_pospuestas`) para que
   "se vendieron 2 y pasaron 3 de ayer, se piden 5" se pueda verificar de un
   vistazo. El producto entra a la lista siguiente **aunque no se haya vuelto
   a vender**.
5. **"El día siguiente" es la siguiente lista que se arme**, no el siguiente
   día del calendario: un sábado pasa al lunes, igual que las ventas (ADR
   0020, regla 4). Pasa **una vez**: si mañana tampoco se pide, se puede
   volver a pasar —y entonces lleva lo de ayer sumado, sin contarlo dos
   veces—, o se queda sin pedir y corre la regla del ADR 0020.
6. **Lo que viene en camino le gana**, igual que a `faltaron`: si el producto
   ya está en tránsito cuando se arma la lista siguiente, lo pospuesto no se
   suma.
7. **Un pospuesto no es "algo que se perdería".** Al cerrar —a mano o solo—
   no se señala: ya tiene adónde ir.
8. **No cuenta en el total ni en el reparto por proveedor de hoy**, igual que
   un descartado. Es justo para lo que existe: bajar el total.

## Opciones descartadas

- **Reabrir la opción 2 del ADR 0020 tal cual: arrastrar todo lo no pedido.**
  Lo que el ADR 0020 temía sigue siendo cierto: la encargada no descarta lo
  que no le sirve, y la sección arrastrada crecería todos los días. Aquí pasa
  solo lo que una persona eligió, uno por uno.
- **Descartar con una marca de "para mañana".** Un solo estado con dos
  significados opuestos, y todas las reglas que hoy leen `descartado`
  —cierre, conciliación, el bloque de descartados— tendrían que aprender a
  separarlos.
- **Bajar la cantidad del renglón y recordar la diferencia.** Mezcla dos
  decisiones —"pido menos" y "el resto mañana"— en un mismo campo, y el número
  pospuesto no se podría devolver con un clic.
- **Un tope de dinero en la pantalla, que recorte solo.** Es lo que de verdad
  está detrás del pedido del dueño, pero el tope cambia según el día y lo
  decide él en el momento. El recorte lo hace una persona; la pantalla solo
  le da el botón.

## Consecuencias

- El renglón tiene un séptimo estado. La migración amplía el `CHECK` de
  `estado` y agrega la firma del pospuesto y `piezas_pospuestas` en el renglón
  nuevo, con su `CHECK` (la regla 6 de `CLAUDE.md`: el rol `continental` ya
  escribe en `renglon`; no hace falta un permiso nuevo).
- La conciliación (ADR 0021) no busca la compra de un pospuesto en la ventana
  de hoy: no se iba a comprar hoy. Se busca en el renglón de mañana, donde ya
  viene sumado.
- **Condición de revisión:** si los pospuestos se vuelven a pasar día tras día
  sin pedirse —se ve contando renglones con `piezas_pospuestas` que vuelven a
  quedar `pospuesto`—, el botón se está usando como un "luego" sin fin, y hay
  que pensar en un tope de veces o en un aviso.

## Enmienda 2026-10-05 — de "pasar al día siguiente" a la lista de espera, con el mínimo del proveedor

**Decisión del dueño, el mismo día, después de ver la pantalla de captura.**
El tope de dinero no es el único motivo para no pedir hoy: cada proveedor
tiene un **mínimo** para surtir un pedido, y un pedido chico se queda esperando
a que se junte más. Para eso "pasa una vez, a la siguiente lista, y se vuelve
a repartir" se queda corto: se pierde a quién se le iba a pedir y no hay forma
de juntar varios días.

Cambia lo siguiente; lo que no se nombra aquí sigue como arriba.

1. **El nombre.** El botón dice **«Mandar a espera»**, el renglón **«En
   espera»** y el conjunto es la **Lista de espera**. `pospuesto` se queda como
   el nombre del estado en la base: renombrarlo es una migración sin ganancia.
2. **Conserva el proveedor.** Mandar a espera guarda a quién se le iba a pedir.
   Cuando se arma la lista siguiente, lo que espera **entra solo al pedido de
   ese proveedor**, ya repartido, en vez de volverse a repartir (cambia la
   regla 4 en ese punto: las piezas se siguen sumando igual).
3. **Si el producto se vuelve a vender, se junta** en un solo renglón con el
   proveedor de la espera. Si otro lo da más barato, la tarjeta lo dice y una
   persona decide; partir un producto en dos renglones complicaba la captura.
4. **No caduca mientras espera.** Se quita "pasa una vez" (regla 5): se puede
   mandar a espera tantas veces como haga falta, y cada renglón dice desde
   cuándo espera y cuántas listas lleva. Eso cumple la condición de revisión de
   arriba de otra forma: no se pone un tope de veces, se pone a la vista.
5. **En cuanto entra a una lista, es un renglón como cualquier otro.** Si esa
   lista se cierra sin que nadie lo pida ni lo vuelva a mandar a espera, se da
   por atendido (ADR 0020). **Se avisa al cerrar**: cambia la regla 7 solo
   para lo que *vino* de la espera, porque reabrir (ADR 0016) deja de servir en
   cuanto se arma la lista siguiente, y sin el aviso eso se perdería callado.
6. **También el pedido entero.** En la pantalla de captura, cada pedido lleva
   «Mandar a espera», que manda **solo los renglones no tachados** y dice
   cuántos se quedaron: lo tachado ya está en el carrito del portal. El botón
   por renglón se queda en Revisar y se agrega en Captura.
7. **El mínimo del proveedor** se captura a mano en una pestaña nueva,
   **Ajustes**: uno por proveedor, **tal como lo dice el proveedor** —con una
   marca de si incluye IVA—, firmado y sin historial. Un pedido debajo del
   mínimo **se avisa, no se bloquea**: a veces conviene pagar el flete. Un
   proveedor sin mínimo capturado dice "sin mínimo capturado", nunca un cero.

### Opciones descartadas

- **Dos botones, "mañana" y "lista de espera".** Dicen casi lo mismo y los dos
  nacen del mismo recorte; en el mostrador se iban a confundir.
- **Una lista de espera aparte que alguien revisa a mano.** Lo guardado
  dependería de que alguien se acuerde de ir a verla, que es justo lo que se
  quiere evitar.
- **Que lo no atendido regrese solo a la espera al cerrar.** Era la opción
  recomendada; el dueño prefirió que una lista cerrada dé por atendido lo que
  nadie tocó, igual que todo lo demás, y que el aviso al cerrar sea la red.
- **Bloquear «Enviar» debajo del mínimo.** El mínimo lo pone el proveedor pero
  la excepción la decide una persona.
- **Guardar el mínimo siempre sin IVA, convertido.** Obliga a hacer la cuenta
  al capturarlo, y es justo la resta entre con y sin IVA que ya volteó una
  flecha en Marlowe.
