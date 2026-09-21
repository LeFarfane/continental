# 27: Recibido parcial y marcado manual

**Qué construir:** el caso real de todos los días: el proveedor manda la mitad. Lo que no llegó tiene que volver a la lista solo, y lo que el sistema no pudo emparejar tiene que poderse cerrar a mano.

**Bloqueado por:** 26.

**Status:** ready-for-human

- [x] Se puede indicar cuántas piezas llegaron de un renglón.
- [x] Si llegó menos, el renglón queda `recibido parcial` y **la diferencia vuelve a proponerse** en el siguiente pedido sugerido.
- [x] Se puede marcar un renglón como recibido a mano, sin propuesta del sistema: un pedido puede llegar en dos facturas, y SICAR no tiene estado parcial (`status` solo vale 1 o -1).
- [x] Un pedido cuyos renglones llegaron todos queda `recibido`; si alguno quedó corto, `recibido parcial`.
- [x] Todo marcado manual queda firmado con quién y cuándo.

> **La cuarta casilla se lee con cuidado a propósito** (ADR 0015): el pedido
> "queda" `recibido` o `recibido parcial` **a la vista** —se calcula de sus
> renglones cada vez que se mira—; en la tabla sigue diciendo `enviado`, que es
> lo que una persona declaró y sigue siendo verdad.

## Qué lo cumple

1. **Cuántas llegaron.** Columna nueva `renglon.piezas_recibidas`
   (`numeric(12,3)`, migración **0011**) y `RenglonGuardado.piezas_recibidas`
   (`src/continental/almacenamiento.py:700`). La escriben las tres salidas: a
   mano (`_RECIBIR_A_MANO`, `almacenamiento.py:3891`), parcial con la
   evidencia (`_RECIBIR_PARCIAL_CON_COMPRAS`, `:3846`) y —desde hoy también—
   confirmar (`_CONFIRMAR_LA_RECEPCION`). La persona la escribe en
   `POST /api/renglon/{id}/recepcion/a-mano` (`web/app.py:1726`), y se valida
   en el servidor con `recepcion.piezas_escritas` (`recepcion.py:673`):
   entero, de 1 en adelante, tope 99,999; **más de lo pedido se acepta**.
2. **`recibido parcial` y la diferencia vuelve.** El estado sale de las piezas
   (`case` en la sentencia, `recepcion.estado_por_las_piezas`, y
   `ck_renglon_completo_o_parcial` en la tabla). Lo que faltó
   (`RenglonGuardado.lo_que_falto`, `almacenamiento.py:708`) vuelve **como
   piezas**: `LoYaPedido.piezas_que_vuelven` (`:1098`) →
   `MemoriaDeLoPedido.faltaron` (`transito.py:161`, llenado en `:251`) →
   `calcular_pedido_sugerido(faltaron=)` las suma a lo vendido
   (`sugerido.py:413`), y el renglón nuevo guarda cuántas trae en
   `piezas_que_faltaron` (columna nueva, CHECK
   `ck_renglon_piezas_que_faltaron`). La pantalla lo dice en el renglón.
3. **A mano, sin propuesta, y en dos facturas.** Cada renglón en camino tiene
   su "Recibir a mano" en el bloque de la recepción —con propuesta o sin ella;
   la frase del 26 que decía "todavía no se puede" es ahora
   `recepcion.SALIDA_A_MANO` (`recepcion.py:134`)—. **Lo que se escribe es el
   total**: la segunda factura se captura corrigiendo la cifra (6 → 10), con
   `_CORREGIR_LO_RECIBIDO` (`almacenamiento.py:3933`), mientras lo que faltó no
   lo haya atendido una lista posterior. Una propuesta del 26 que trae de
   menos se recibe parcial con su evidencia:
   `POST /api/renglon/{id}/recepcion/parcial` (`web/app.py:1694`).
4. **El pedido.** `recepcion.estado_del_pedido` (`recepcion.py:736`) y su
   frase (`:768`); viajan en `estado_a_la_vista` y `frase_de_la_recepcion` del
   pedido (`web/app.py:3151`), y la pantalla los pinta. Un pedido con algo
   recibido parcial sigue sin cancelarse (el `NOT EXISTS` del 25).
5. **Firmado.** `recibido_por` y `recibido_en` con el correo de Access (firma,
   nunca permiso), y **sin compras**: `recibido_con_compras` en `NULL` es "a
   mano". La frase lo dice: *"lo dijo X el jueves a las 11:00, a mano, sin
   compra de SICAR que lo sostenga"* (`recepcion.frase_de_lo_recibido`,
   `recepcion.py:584`). Al corregir, la firma pasa a quien dijo la cifra
   guardada; la de antes queda en la bitácora.

Pruebas: `tests/test_parcial.py` (109) más 1 que `test_compila.py` gana sola por
la migración 0011. Recorrido del navegador con los dobles: hecho, y cazó tres
(abajo).

## Las cinco decisiones, a propósito (ADR 0015)

1. **La diferencia vuelve como piezas, aparte de lo vendido mientras venía.**
   Lo vendido mientras venía vuelve por el ancla (ADR 0012), lo que faltó son
   ventas *de* la ventana original: conjuntos disjuntos, ninguna venta dos
   veces. Pedí 10, llegaron 6; martes 3, miércoles 2, jueves 1: la del jueves
   propone 3 + 2 + 1 + 4 = **10**, la del viernes **1**.
2. **El estado del pedido se calcula**, no se guarda: es un hecho derivado, y
   guardado rompería cuatro `WHERE` que exigen `p.estado = 'enviado'`.
3. **Se escribe el total**: recibir, completar con la segunda factura y
   corregir un error son la misma pregunta; se corrige mientras nadie haya
   atendido lo que faltó.
4. **Cancelar después de un parcial sigue prohibido**: llegó algo, luego sí se
   capturó. No cambió una línea.
5. **La propuesta que trae de menos se recibe parcial** con su evidencia, con
   las garantías de confirmar y la cantidad al revés.

## Lo aprendido

- **El recorrido del navegador cazó tres, la octava vez** (14, 15, 21, 22, 24,
  25, 26, 27), y las tres tienen prueba:
  - lo que llegó de menos decía *"vuelve en la siguiente lista"* debajo de una
    lista de hoy que ya lo traía;
  - la segunda factura, corregida **después** de armar la lista de hoy, dejaba
    el renglón de hoy pidiendo las piezas que ya llegaron sin decir nada —el
    mismo borde que "ya viene en camino" del 24—; ahora lo avisa en ámbar;
  - el **hilo abierto 18** se disparó (este ticket tocó `pintarParticion`) y
    además empeoraba: con lo recibido, la reserva decía *"se pidió entera… sus
    renglones están en tránsito"* sobre renglones que ya llegaron. Ahora la
    frase del caso mixto es de Python y el título dice "se pidió en parte".
- **`recepcion.py` sí puede importar `almacenamiento`**: el 26 lo evitó con
  `TYPE_CHECKING`, pero no hay ciclo (`almacenamiento` → `sugerido` →
  `transito` solo en tipos). Ahora importa los estados de verdad.
- **Una llave de JSON con "parcial" tumbaba la prueba del 26** que impide
  componer frases en `pintarRecepcion` (busca la palabra en todo el cuerpo).
  Las llaves se llaman `se_puede_recibir_lo_que_trae` y
  `etiqueta_de_lo_que_trae`; la prueba vieja no se tocó.
- **`git stash` en esta torre reescribe los archivos modificados con CRLF**
  (`core.autocrlf=true`, y `.gitattributes` solo fija `eol=lf` para `.sh`,
  `.service`, `.timer` y `.sql`). Los `.py` y el `.html` quedaron con CRLF y
  los reemplazos exactos dejaron de encontrar su texto. Se devolvieron a LF.
  **No uses `git stash` para medir**: usa `git worktree` o cuenta sin él.
- **Las pruebas viejas que ponían `recibido` a pelo en el doble**
  (`test_ajuste`, `test_descarte`, `test_cancelar`, `test_transito`) ahora
  dicen cuántas llegaron, porque `ck_renglon_completo_o_parcial` lo exige: son
  más estrictas, no menos.

## Lo que quedó sin hacer, y por qué

- **La recepción no propone completar un parcial.** Si la segunda factura
  aparece en SICAR, no se ofrece "el resto probablemente llegó": `proponer`
  solo mira lo que está en tránsito. La salida es corregir la cifra a mano.
  Proponerlo pide decidir contra qué compras se cruza un renglón ya recibido
  y cómo no reusar las que ya sostienen su recepción; es otro ticket.
- **Lo recibido completo de listas anteriores no se corrige desde la
  pantalla**: se enseña para corregir lo de hoy (en la tabla) y lo que llegó
  de menos y nadie atendió (en el bloque de lo que viene). Un `recibido` de
  una lista vieja que resulta ser parcial se corrige por la ruta, no hay
  botón. Sin caso visto todavía.
- **La firma de cada corrección no se guarda**, solo la última
  (`recibido_por`); la bitácora tiene todas. Guardarlas pedía una tabla y
  volver a correr `crear_rol.sql`.
- **La celda de la cantidad** sigue diciendo "se vendieron 1" junto a un 3
  cuando el renglón trae 2 que faltaron: es verdad, y la frase del producto
  explica la suma, pero la cuenta no se escribe en la celda. Componerla en el
  JavaScript sería justo lo que la lección del 15 prohíbe.
- **El estado del pedido no se puede filtrar con un `WHERE`** sobre
  `pedidos.pedido`. Si un reporte lo necesita, es un `GROUP BY` sobre sus
  renglones.
- **`continental.verificar` no revisa lo recibido.** Los CHECK de la 0011 ya lo
  garantizan en la tabla; un invariante sobre datos (p. ej. un parcial viejo
  que nadie atiende) no lo pidió el ticket.
- **Nada de esto corrió contra Postgres**: desde la torre no hay uno. La
  0011 va antes de desplegar; `crear_rol.sql` **no** se vuelve a correr.
