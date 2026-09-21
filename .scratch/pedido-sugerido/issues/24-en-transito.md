# 24: En tránsito

**Qué construir:** la memoria de lo ya pedido. Es lo que arregla el problema que hoy existe: si el martes se piden 3 piezas y llegan el jueves, el miércoles el producto sigue vendido y con existencia baja, y se vuelve a pedir.

**Bloqueado por:** 09 · 21.

**Status:** ready-for-human

- [x] Un renglón `en tránsito` **no** vuelve a proponerse en el siguiente pedido sugerido.
- [x] Los renglones en tránsito se ven en algún lado, con su proveedor y la fecha en que se enviaron.
- [x] Si el mismo producto se vuelve a vender mientras está en tránsito, esa venta no se pierde: queda contabilizada para cuando el renglón se cierre.
- [x] La pantalla del día muestra los renglones en tránsito atenuados con "pedido el martes, sin recibir" en vez de esconderlos: un hueco visible es información.
- [x] Queda claro que esto solo protege si el pedido pasó por Continental: un pedido capturado por fuera se va a proponer otra vez.

## Qué lo cumple

1. **No se vuelve a proponer.** `transito.MemoriaDeLoPedido.recortar` saca de
   la lista todo producto con un renglón `en tránsito`; `sugerido.armar_la_lista`
   la **exige** (sin valor por omisión: olvidarla sería pedir dos veces en
   silencio) y la pantalla y el lote la leen con `lo_ya_pedido` **dentro** de
   `armar`. Si esa lectura falla, la lista no se arma: hueco con su motivo.
2. **Se ven.** El bloque "en camino" de la pantalla (`transito.en_camino_como_json`):
   producto, piezas, proveedor, cuándo (`cuando_se_envio`), quién lo marcó y a
   qué hora, de qué lista salió (`frase_de_la_firma`).
3. **La venta no se pierde.** ADR 0012. La venta se queda en `marts.fct_ventas`;
   el ancla es la `ventas_consideradas_hasta` de la lista del renglón en
   tránsito. Al pasar a `recibido`/`recibido parcial`, la siguiente lista cuenta
   el producto **desde el día siguiente al ancla** aunque el corte haya avanzado
   encima, y el renglón lo dice (`renglon.ventas_desde`, migración 0008, y
   `frase_de_la_ventana_propia`). Mientras tanto, el bloque dice cuánto se lleva
   vendido desde que se pidió.
4. **Atenuados.** `tr.transito`/`li.transito` con `opacity: .62`, y la frase de
   Python: *"Pedido el martes a NADRO, sin recibir."* — hoy, ayer, el día de la
   semana hasta seis días, y desde siete la fecha con cuántos días lleva.
5. **Solo protege lo que pasó por aquí.** `transito.ADVERTENCIA_DE_LO_QUE_PROTEGE`,
   en el bloque, **siempre** —también cuando no viene nada en camino, que es
   cuando un bloque vacío más engaña—.

Pruebas: `tests/test_transito.py` (82). Recorrido del navegador con los dobles:
hecho, y cazó una (ver abajo).

## Lo aprendido

- **El doble pedido existía sin ninguna venta nueva.** Una lista que se envía y
  no se cierra no mueve el corte, así que la del día siguiente vuelve a recoger
  sus días por el piso del ticket 09 — con lo ya pedido sumado dentro del mismo
  número. Era el caso más directo y el ticket no lo nombraba.
- **Filtrar solo es la trampa de la tercera casilla.** Con la ventana que avanza
  en cada cierre, un día que se cerró con el producto fuera no lo vuelve a mirar
  nadie. La salida no fue guardar ventas: fue guardar **desde dónde volver a
  leerlas**, y ese dato ya existía.
- **El ancla recorta en los dos sentidos.** Al recibirse, el producto se cuenta
  desde el día siguiente al ancla: a veces eso es **antes** de la ventana (trae
  lo retenido) y a veces **después** (la lista de aquel pedido no se cerró, y
  esos días ya estaban pedidos).
- **Un recibido se deja de recordar cuando una lista posterior CERRADA lo trae,
  o cuando se vuelve a pedir.** Si la lista que lo trajo no se cierra, se vuelve
  a traer — el mismo comportamiento que el piso del 09 con una lista vencida.
- **El día de la semana se calcula en la hora de la farmacia**, no en UTC: un
  envío del lunes a las 20:30 son las 02:30 del martes en el contenedor. UTC-6
  fijo (sin horario de verano desde 2022; la torre no tiene `tzdata`).
- **`app.py` no puede mirar el reloj** —hay una prueba en `test_sugerido.py` que lo
  vigila—, y aquí hacía falta uno para "hace cuánto se envió". El reloj entró a
  `web/dependencias.reloj`, con los otros bordes; `app._ahora` lo envuelve para
  que una prueba lo fije.
- **El recorrido del navegador cazó una, la quinta vez (14, 15, 21, 22, 24).**
  La firma del envío se armaba en el JavaScript pegándole un punto a
  `instanteEnPalabras`, que ya termina en "a.m.": *"11:00 a.m.."* — el mismo
  tropiezo del 21. Además vivía en un `title`, que en una pantalla táctil no se
  ve. Ahora es `frase_de_la_firma`, en Python, a la vista y con prueba.
- **El bloque se pinta una vez, al cargar**, y se conserva cuando partir,
  enviar o tachar sustituyen la lista entera (`conservarLoDeLaCarga`): esas
  rutas no lo leen porque no lo cambian. Lo mismo el aviso "ya viene en camino"
  cuando una ruta de un solo renglón lo sustituye.

## Lo que quedó sin hacer, y por qué

- **Cancelar** no cierra el tránsito aquí: es el ticket 25, y su regla es otra
  —lo que vuelve es **también** lo que el renglón repuso, porque nunca llegó—.
  `ESTADOS_QUE_CIERRAN_EL_TRANSITO` lo deja fuera a propósito (ADR 0012).
- **La diferencia de un recibido parcial** (lo que no llegó) no se suma aquí:
  es el ticket 27. Lo que sí pasa ya con `recibido parcial` es que vuelve lo
  vendido después del ancla.
- **El borde que la memoria no alcanza se avisa y no se corrige.** Si se envía
  un pedido desde una lista vencida **después** de que la de hoy se armó con el
  mismo producto, la de hoy no se recalcula (lo que se muestra es lo guardado);
  su renglón lo dice en ámbar. Recalcular una lista guardada sería otra decisión.
- **Las ventas del mismo día del ancla que llegan tarde** se consideran
  cubiertas por aquel pedido. Es el mismo pedacito que ya pierde el corte (hilo
  abierto 6 de `HANDOVER.md`) y se resolvería igual: con hora en el almacén.
- **La migración 0008 no se ha corrido en ninguna parte**, igual que las siete
  anteriores: el almacén vive en atlas y desde la torre no hay Postgres. Va
  **antes** de desplegar este código.
