# 26: Recepción sugerida

**Qué construir:** que el encargado no tenga que marcar a mano lo que SICAR ya sabe. Cuando la compra se captura, el sistema propone que ese renglón llegó, pero **no lo afirma**.

**Bloqueado por:** 24.

**Status:** ready-for-human

- [x] Una función pura recibe los renglones en tránsito y las compras posteriores, y devuelve propuestas con su evidencia: proveedor, producto, cantidad y fecha de la compra.
- [x] El emparejamiento es por proveedor, producto y fecha posterior al envío. **Nunca por folio**, cuya semántica no está verificada (nadie sabe si es el consecutivo de SICAR o el número de factura del proveedor).
- [x] El renglón queda **probablemente recibido** y espera un clic; jamás pasa solo a `recibido`.
- [x] La pantalla muestra en qué se basó la propuesta, para que la persona pueda juzgarla.
- [x] Confirmar lo pasa a `recibido`; rechazar lo devuelve a `en tránsito`.
- [x] Con una noche de retraso: la compra aparece en el almacén hasta la cadena siguiente, y eso es normal, no un error.
- [x] 606 de 3,429 artículos (17.7%) nunca aparecen en compras: para ésos nunca va a haber propuesta, y el marcado manual del ticket 27 es su única salida.

> **Dos palabras de las casillas se leen con cuidado a propósito**, y el ADR
> 0014 dice por qué: "el renglón queda *probablemente recibido*" no es un
> estado guardado —es una propuesta que se calcula cada vez que se mira—, así
> que "rechazar lo devuelve a `en tránsito`" es literal: **nunca dejó de
> estarlo**.

## Qué lo cumple

1. **La función pura.** `src/continental/recepcion.py`, `proponer` — recibe lo
   que está en tránsito (`LoYaPedido`, ahora con el `pro_id` de su pedido) y las
   `LineaDeCompra` del almacén, y devuelve una `Recepcion` con `Propuesta`s —la
   evidencia entera: cada compra con su proveedor, producto, cantidad y fecha— y
   `SinPropuesta`s con su motivo (seis). Lo que está en tránsito sale de una
   lectura nueva, `almacenamiento.lo_que_esta_en_transito` (`_EN_TRANSITO`), que
   **incluye la lista de hoy**: lo pedido a las 9 puede llegar a las 15.
2. **Proveedor, producto, fecha; nunca folio.** `recepcion._encaja`. El día del
   envío es el **de la farmacia** (`dia_del_envio`, UTC-6 fijo, calculado en
   Python: en Postgres `at time zone '-06'` se lee UTC+6) y **el mismo día
   cuenta**. El folio solo se **enseña** en la evidencia, con la frase de que no
   se usó; hay una prueba que lee el código y se pone roja si `.folio` aparece
   en una comparación.
3. **Espera un clic.** Nada escribe `recibido` salvo `_CONFIRMAR_LA_RECEPCION`,
   detrás de `POST /api/renglon/{id}/recepcion/confirmar`. La propuesta no se
   guarda en ninguna columna.
4. **La evidencia a la vista.** El bloque `#recepcion` (arriba de lo que viene en
   camino): por renglón, la frase de *probablemente*, cuándo y a quién se pidió,
   cada compra dicha con palabras —a quién, qué día, cuántas piezas, cuántos días
   después del envío, y el folio—, lo que trae contra lo que se pidió, y si la
   misma compra le sirve a otro renglón. Todo compuesto en Python
   (`recepcion_como_json`).
5. **Confirmar y rechazar.** Dos rutas, firmadas con el correo de Access (firma,
   nunca permiso). La ruta **vuelve a calcular la propuesta** y contesta 409 si
   ya no es la que la persona vio. Confirmar → `recibido` + `recibido_por`,
   `recibido_en`, `recibido_con_compras`; con eso lo retenido del ticket 24
   vuelve solo (`ESTADOS_QUE_CIERRAN_EL_TRANSITO`). Rechazar → sigue en
   tránsito; esas compras se agregan a `compras_rechazadas` con la firma del
   último rechazo, y no se vuelven a proponer.
6. **Una noche de retraso.** `recepcion.AVISO_DEL_RETRASO` va **siempre** en el
   bloque —también cuando todo tiene propuesta—, y el motivo `todavía no
   aparece` lo dice "normal, no un error".
7. **Los que nunca van a tener propuesta.** Dos motivos que se enseñan
   **primero**: `nunca en compras` (lectura nueva del almacén,
   `productos_con_compras`, sobre la misma `fct_compras` que el rol ya lee; si
   falla, no se afirma "nunca") y `sin puente` (QuePharma, ADR 0008). La frase
   dice que su única salida es el recibido a mano **y que todavía no existe** en
   esta pantalla, en vez de pintar un botón que no hay.

Pruebas: `tests/test_recepcion.py` (92) más 2 que `test_compila.py` gana sola.
Recorrido del navegador con los dobles: hecho, y cazó cuatro (abajo).

## Las cinco decisiones, a propósito (ADR 0014)

1. **Propuesta calculada, no estado guardado.** Si la compra desaparece del
   almacén, la propuesta desaparece con ella; un estado guardado la seguiría
   afirmando, y además sacaría el renglón de `en tránsito` y su producto se
   volvería a proponer antes de que nadie confirmara. Lo que sí se guarda son
   las dos decisiones de la persona, en seis columnas de `pedidos.renglon`
   (migración 0010). **El rechazo guarda qué compra, no una fecha tope**: una
   del viernes capturada a las 19:30 llega el lunes y una fecha tope la
   escondería.
2. **Cantidades.** Se enseñan siempre. Solo se confirma si la evidencia trae al
   menos lo pedido (`recibido` es "llegó completo"); la condición está en la
   función pura y en el `WHERE` (`:piezas`). Con menos, se dice que es un
   parcial y no se ofrece el clic. Dos facturas del mismo producto se suman.
3. **Una compra que encaja con dos renglones** se propone en los dos, cada uno lo
   dice, y el `WHERE` impide que confirme dos (`&&` contra
   `recibido_con_compras`).
4. **Proveedor sin puente**: nunca habrá propuesta, y se dice.
5. **La fecha**: día de la farmacia, en Python; el mismo día del envío cuenta.

## Lo aprendido

- **`ck_renglon_recepcion` exige firma también para `recibido parcial`.** Es la
  puerta del 27, y costó ajustar cinco pruebas viejas que ponían `recibido` a
  pelo en el doble: ahora firman.
- **`_LO_YA_PEDIDO` no sirve para la recepción**: mira solo listas anteriores
  porque es la memoria con la que se arma una lista. Hizo falta una hermana sin
  fecha de lista.
- **La recepción ejercita por primera vez el GRANT de `marts.fct_compras`.** Si
  un `dbt build` se lo llevó, el bloque sale como hueco con su motivo y la
  lista sigue.
- **El recorrido del navegador cazó cuatro**, la séptima vez: *"Trae las 1 pieza
  que se pidieron"*; *"siguen en camino"* debajo de un solo renglón (las frases
  de grupo ahora concuerdan en número); el motivo de no confirmar repetido debajo
  de la frase de la cantidad; y un renglón recibido que seguía contando *"por
  atender"*. Las cuatro tienen prueba.

## Lo que quedó sin hacer, y por qué

- **El recibido parcial y el marcado a mano** son el ticket 27. Lo de aquí les
  deja la puerta abierta: el CHECK ya pide firma para `recibido parcial`,
  `recibido_con_compras` admite `NULL` en lo recibido, y la frase
  `FALTA_EL_MARCADO_MANUAL` es la que el 27 tiene que cambiar.
- **Una compra que de verdad surtió dos pedidos** (10 piezas para dos de 5) solo
  confirma uno; el otro espera el marcado a mano. Repartir piezas sería afirmar
  lo que SICAR no sabe.
- **La firma del rechazo es la del último**: guardar una por compra pedía una
  tabla nueva y volver a correr `crear_rol.sql`. La bitácora tiene cada rechazo.
- **La partición que dice "ya se pidió entera" con un renglón sin proveedor**
  no es de este ticket (texto de reserva del 21); quedó como hilo abierto 18 de
  `HANDOVER.md`.
- **Nada de esto corrió contra Postgres**: desde la torre no hay uno. La 0010 va
  antes de desplegar; `crear_rol.sql` **no** se vuelve a correr.
