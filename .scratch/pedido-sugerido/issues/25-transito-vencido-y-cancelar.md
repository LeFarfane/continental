# 25: Tránsito vencido y cancelar un pedido

**Qué construir:** la válvula de escape. Un renglón en tránsito que nunca llega se queda fuera de la lista para siempre, y eso es mercancía que va a faltar sin que nadie lo note.

**Bloqueado por:** 24.

**Status:** ready-for-human

- [x] Un renglón que lleva más de N días en tránsito se señala como vencido, con el número de días a la vista. N se configura, no va escrito en el código.
- [x] Un pedido que nunca se capturó se puede cancelar, y sus renglones vuelven a `abierto` para el siguiente sugerido.
- [x] Cancelar queda firmado con quién y cuándo.
- [x] Un renglón en tránsito vencido se puede devolver a la lista uno por uno, sin cancelar el pedido completo.

> **Dos palabras de las casillas cambiaron a propósito**, y el ADR 0013 dice por qué:
> "vencido" es **atrasado** (vencido ya es un estado de la lista) y "vuelven a
> `abierto`" es **vuelve su producto, en la siguiente lista** (el renglón pasa a
> `cancelado`: su lista casi siempre está cerrada y no se modifica).

## Qué lo cumple

1. **Atrasado, con los días a la vista, N en el YAML.** `config/continental.yml`,
   `pedido.dias_en_transito_para_atrasado: 7`, con su comentario (no está
   medido; por qué siete; condición de revisión). Lo lee
   `almacenamiento.dias_en_transito_para_atrasado_configurados`, que **truena**
   si falta o no es un entero ≥ 1 —la pantalla lo enseña como hueco con su
   motivo—. La señal es **calculada, no un estado**: `transito.dias_en_transito`
   (días de calendario de la farmacia, UTC-6), `esta_atrasado` (**más** de N),
   `frase_del_atraso` ("Atrasado: lleva 10 días en camino, más de 7 días…"). Va
   en cada renglón del bloque de lo que viene en camino y en los renglones en
   tránsito de la lista del día.
2. **Cancelar un pedido que nunca se capturó.** `POST /api/pedido/{id}/cancelar`
   → `almacenamiento.cancelar_el_pedido`: `_CANCELAR_EL_PEDIDO`
   (`enviado` → `cancelado`, con `NOT EXISTS` sobre lo recibido) y
   `_RENGLONES_CANCELADOS` (`en tránsito` → `cancelado`), en una transacción. El
   producto vuelve en la siguiente lista **desde el principio de lo que el
   renglón cubría** (`LoYaPedido.retiene_desde`), con la memoria del 24:
   `_LO_YA_PEDIDO` trae lo `cancelado` que nadie ha atendido. Se ofrece en el
   pedido enviado de hoy (la partición) y en los de listas anteriores (el
   bloque de lo que viene en camino), con la frase de lo que se declara junto
   al botón (`transito.frase_para_cancelar`).
3. **Firmado.** `pedido.cancelado_por`/`cancelado_en` y
   `renglon.cancelado_por`/`cancelado_en`, pareadas contra el estado por
   `ck_pedido_cancelacion` y `ck_renglon_cancelacion` (migración 0009), con el
   correo de Access —firma, nunca permiso: sin encabezado firma
   `sin-identificar`—.
4. **Devolver uno por uno.** `POST /api/renglon/{id}/devolver-atrasado` →
   `almacenamiento.devolver_el_atrasado`: `_DEVOLVER_EL_ATRASADO` pasa **ese**
   renglón a `cancelado` solo si su pedido se envió antes de
   `transito.enviado_antes_de(ahora, N)` —el mismo límite con el que la pantalla
   decide ofrecer el botón, como parámetro del `WHERE`—. El pedido sigue
   `enviado`.

Pruebas: `tests/test_cancelar.py` (95), más siete ajustadas en archivos viejos
porque los estados crecieron (ver abajo). Recorrido del navegador con los dobles:
hecho, y cazó dos.

## Las tres tensiones, resueltas a propósito

1. **El ADR 0009 dijo que no hay "desenviar".** Sigue sin haberlo. `cancelado` es
   un tercer estado, **terminal y hacia adelante**: no vuelve a `borrador`, no se
   edita, no se vuelve a enviar, no se descancela. El 0009 lleva una nota de
   enmienda que dice exactamente qué cambió (y qué no), y el 0013 lo razona.
2. **"Vencido" ya era de la lista.** Lo del renglón se llama **atrasado**, y no
   es un estado: se calcula cada vez contra el instante del envío. `CONTEXT.md`
   tiene el término, con la nota de que no es vencido.
3. **Lo que el renglón cubría vuelve, una sola vez.** Un renglón cancelado nunca
   repuso nada: su producto se cuenta desde su `ventas_desde` o desde el principio
   de su lista, no desde el día siguiente al ancla. No se duplica porque la
   memoria usa **un solo intervalo por producto**, se **olvida** en cuanto una
   lista posterior cerrada lo trae o el producto se vuelve a pedir (o a
   cancelar), y lo en camino le gana. Escenarios de varios días en
   `test_cancelar.py`: con las listas de en medio cerradas (3 + 2 + 1 = 6, y al
   día siguiente 1), sin cerrar (6 por el piso del 09, sin sumar dos veces), el
   mismo día (vuelve mañana: 3 + 2 = 5), y dos semanas con un atrasado devuelto
   (3 + 4 + 1 + 1 = 9, y al día siguiente 1), más el lote nocturno.

   Y la cuarta que el ticket traía sin notarla: el renglón **no** vuelve a
   `abierto` en su lista vieja —casi siempre cerrada, y solo una lista abierta se
   modifica; sus ventas además se perderían detrás del corte—. Lo que vuelve es
   el producto, a la siguiente lista.

## Lo aprendido

- **`at time zone '-06'` en Postgres es POSIX: se lee como UTC+6.** Por eso el
  límite del atraso se calcula en Python (`enviado_antes_de`, medianoche de la
  farmacia) y viaja como parámetro. Una prueba recorre doce días de hora en hora
  con tres umbrales para que la pantalla (`dias_en_transito`) y el `WHERE` no se
  separen ni un instante.
- **Un tercer estado del pedido rompe `!fue_enviado`.** La pantalla usaba "no
  enviado" como "borrador" para pintar la captura, el botón de enviar y el motivo
  para no enviar. Con `cancelado` eso le pintaba casillas a un pedido que ya no
  existe en ningún portal; ahora es `es_borrador`. Y `motivo_para_no_enviar`
  habría dicho que un cancelado **sí** se puede enviar (tiene renglones dentro):
  `fue_enviado` se separó de `not es_borrador` en el 21 esperando justo esto.
- **Hasta el ticket 26, lo que llegó también se ve atrasado**: nada lo pasa a
  `recibido`. Devolver a la lista lo que sí llegó es volverlo a pedir entero. La
  advertencia va junto al botón, y es la razón principal de que N sea una semana
  y no dos días.
- **El recorrido del navegador cazó dos, la sexta vez (14, 15, 21, 22, 24, 25):**
  con todo el pedido de hoy cancelado la partición decía *"Todavía no hay en qué
  partir esta lista · Elige a quién se le pide cada renglón"* sobre renglones que
  ya no se pueden repartir —el mismo tropiezo del 21 con otro estado; ahora la
  frase es `particion.frase_sin_nada_por_repartir`—; y la lista de lo que vuelve
  no tenía encabezado y se leía como parte del pedido de arriba
  (`transito.frase_de_los_que_vuelven`). De paso: "más de 7 días" salía dos
  veces seguidas arriba del bloque.
- **Algunos `.py` del repo están en CRLF y otros en LF** (`particion.py`,
  `sugerido.py`, `config/continental.yml`… sí; `almacenamiento.py`, `app.py`… no).
  Un reemplazo de texto con `\n` falla en silencio contra los primeros: hay que
  respetar el fin de línea de cada archivo.

## Lo que queda sin hacer, con su motivo

- **Volver a pedir hoy lo cancelado hoy.** Quien cancela un pedido de la lista de
  hoy lo tiene de vuelta **mañana**, no hoy: reabrirlo aquí pediría reabrir el
  pedido de ese proveedor en esta lista (`ux_pedido_proveedor`), que es
  desenviar por la puerta de atrás. Condición de revisión en el ADR 0013.
- **Ningún invariante nuevo en `continental.verificar`.** Uno natural sería
  "ningún renglón en tránsito colgando de un pedido cancelado"; las dos
  sentencias van en una transacción y no hay un camino que lo produzca. Si
  aparece un `UPDATE` a mano que lo deje así, ése es el invariante.
- **La frase de los botones** ("Cancelar: no está en el portal de NADRO",
  "Devolver a la lista") se arma en el JavaScript, igual que "Enviar a NADRO —
  $…": es una etiqueta con el nombre del proveedor, no una afirmación. Todo lo
  que afirma algo —días, umbral, qué pasa al apretar, qué vuelve— viene de
  Python.
- **El caso borde del ADR 0009 que la memoria no alcanza** (una lista armada con
  el producto dentro antes de que se enviara el pedido viejo, y después ese
  pedido se cancela) se resuelve con la regla "lo de después atiende a lo de
  antes": si el renglón de la lista de en medio se cerró, lo que el cancelado
  cubría **antes** del principio de esa lista se da por atendido. Es el mismo
  pedacito que ya acepta el ADR 0012 para lo recibido.
