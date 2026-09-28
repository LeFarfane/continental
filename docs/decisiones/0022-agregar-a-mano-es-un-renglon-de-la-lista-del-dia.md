# 0022 — Agregar a mano lo que no se vendió es un renglón más de la lista del día

**Fecha:** 2026-09-28  ·  **Estado:** propuesta — no se construye antes del
primer día real de operación del Pedido, y tiene dos preguntas abiertas al
final
**Complementa el ADR 0002** (el pedido sugerido repone lo vendido)

## Contexto

El pedido sugerido solo sabe proponer **lo que se vendió** (ADR 0002). Hay
compras que no salen de una venta:

- un cliente pide algo que hoy no hay en el anaquel;
- un producto que se agotó hace tiempo y nadie ha vuelto a pedir, así que ya
  no aparece en ninguna lista (nadie lo puede vender si no hay);
- lo que la pestaña de Vigilancia avisa que ya volvió a tener un proveedor.

Hoy esas compras se capturan en el portal **por fuera** de Continental. No
causan un pedido doble —lo que no se vendió no se propone—, pero se pierden
todo lo que el módulo ya hace: la comparación de los cuatro precios, la
captura renglón por renglón, el CSV, el tránsito, la recepción sugerida y la
conciliación.

La pestaña «Órdenes» de Doyle era un carrito para esto: se agregaba un
resultado de búsqueda, con un margen fijo del 25% para calcular el precio de
venta. Quedó inalcanzable el 2026-09-21 con el resto de la interfaz de Doyle
(su ADR 0008). El 2026-09-28 el dueño decidió que la pestaña de Continental se
llama **Pedido** y no «Órdenes», y que agregar a mano se decide con este ADR
antes de construirse.

Lo que ya fija el esquema, medido en `sql/crear_tablas.sql`:

- `ux_renglon_producto UNIQUE (pedido_sugerido_id, producto_id)`: un producto
  aparece una vez por lista.
- `renglon.producto_id` es `NOT NULL`: todo renglón es de un producto que
  SICAR conoce.
- `cantidad_propuesta` admite el cero —*"de esto no se vendió nada", un hecho
  aritmético sin nadie detrás*— y `cantidad_final` no (`>= 1`), con la firma
  del ajuste (`ajustada_por`, `ajustada_en`).

## Opciones consideradas

1. **Revivir el carrito de Doyle** como una pestaña «Órdenes» con su propia
   lista.
2. **Un pedido suelto**, fuera de toda lista: un `pedido` a un proveedor sin
   `pedido_sugerido`.
3. **Un renglón más en la lista del día**, marcado como agregado a mano.

## Decisión

La 3. Un producto que no se vendió entra a la **lista abierta del día** como
un renglón con:

- `piezas_vendidas = 0` y `cantidad_propuesta = 0` —el sistema no propuso
  nada, y es verdad—;
- `cantidad_final = N`, la que escribió la persona, con la firma del ajuste;
- una firma nueva, **`agregado_por` y `agregado_en`**, pareadas por su CHECK:
  dicen que el renglón existe porque una persona lo pidió, no porque se
  vendió.

Desde ahí es un renglón como cualquier otro: se le consulta el precio en los
cuatro, se elige a quién, se parte, se captura, se envía, viaja en tránsito y
se recibe. Cinco reglas más, porque "no se vendió" cambia cinco cosas:

1. **Solo productos del catálogo de SICAR.** El renglón necesita
   `producto_id`, y la recepción empareja compras por producto. Un producto
   nuevo se da de alta en SICAR y aparece aquí después de la cadena de esa
   noche (pregunta abierta 1).
2. **Solo en una lista abierta**, como toda modificación (glosario, 2026-09-20).
   Si la del día ya se cerró, se reabre (ADR 0016) o se espera a la siguiente.
3. **Si el producto ya está en la lista, no se agrega: se corrige su
   cantidad.** Es lo que ya dice `ux_renglon_producto`, dicho con palabras. Si
   viene **en camino** de una lista anterior, se agrega igual pero la pantalla
   lo avisa antes, con cuántas piezas y a quién se pidieron: avisa, no prohíbe
   (el criterio de **cerrar**).
4. **Si su pedido se cancela, vuelve como piezas.** Lo cancelado vuelve
   "contado desde el principio de lo que el renglón cubría" (ADR 0013), y un
   renglón agregado a mano no cubría ninguna venta: sin esta regla, volvería
   *cero*. Así que vuelve como vuelve lo que faltó de un parcial (ADR 0015):
   sus piezas, sumadas a la siguiente lista (pregunta abierta 2). Lo que llegó
   de menos ya funciona sin tocar nada: son las piezas que faltaron.
5. **Cerrar sin pedirlo avisa que se pierde**, igual que lo que faltó de un
   parcial: entra a `cierre.lo_que_se_perderia`. No pasa a la lista
   siguiente.

Se agrega desde dos lugares, con una sola ruta detrás
(`POST /api/pedido-sugerido/{id}/renglon`, `{producto_id, cantidad}`):
desde la pestaña **Pedido**, con el código de barras; y desde un resultado de
**Buscar** que ya diga que es nuestro.

## Razones

- **El carrito (1) sería una segunda manera de pedir.** Una sin tránsito, sin
  recepción, sin captura y sin conciliación, y con un nombre que el dueño ya
  descartó. Su margen fijo del 25% es una versión primitiva del **puente**
  —cuánto margen cabe sin afectar al cliente—, que tiene su propio lugar en
  el orden de trabajo, después del primer día real (ADR 0001, enmienda del
  2026-09-27). Absorberlo aquí sería construir medio puente con otro nombre.
- **El pedido suelto (2) necesitaría su propia vida.** La identidad de un
  pedido es su lista y su proveedor (ADR 0008, `ux_pedido_proveedor`); uno sin
  lista no tiene quién lo cierre ni en qué día contarlo, y la recepción, la
  bitácora navegable (ADR 0020) y la conciliación (ADR 0021) se anclan en la
  lista del día.
- **La 3 no estrena vocabulario.** "Propuesto 0, decidido N, con firma" ya lo
  dice el esquema; lo único nuevo es la firma de quién lo agregó, que es lo
  que distingue un renglón con propuesta cero que la persona trajo de uno que
  el sistema armó.
- **Los precios salen por el camino de siempre**, no de lo que Buscar ya
  trajo. Buscar no empareja (busca por nombre, y VICMA solo vale con un solo
  resultado): congelar ese resultado abriría un segundo camino hacia
  `pedidos.precio_de_proveedor` que se salta `precios.emparejar`. Cuesta
  volver a visitar los cuatro portales (~36 s) por un renglón que alguien
  agregó a propósito; es poco para una sola regla de qué precio vale.
- **No pasar a la lista siguiente** conserva que la lista es de un día (ADR
  0020). Arrastrar renglones entre listas haría que un renglón viviera en dos
  días, y el aviso al cerrar ya cubre que nadie lo pierda sin enterarse.

## Consecuencias

- **Una migración que no crea tabla**: `agregado_por` y `agregado_en` en
  `pedidos.renglon`, con su CHECK pareado y el de "agregado a mano implica
  propuesta cero y cantidad final". `verificar_rol.sql` gana su comprobación.
- **La pantalla lo marca**: "agregado a mano por …" en el lugar donde un
  renglón vendido dice su ventana de ventas; sin ventas, los días de cobertura
  no existen y se dice así, no con un cero. La vista "Todo lo vendido" deja de
  ser exacta y habrá que renombrarla.
- **La conciliación (ADR 0021) cuenta estos renglones aparte.** Mide qué tan
  bien propone el sistema; lo que agregó una persona no es una propuesta
  acertada ni fallida.
- **Lo que no se construye con esto**: productos fuera de SICAR, el margen o
  el precio de venta (eso es el puente), y agregar desde Vigilancia (el aviso
  manda a Buscar, y de Buscar se agrega).

## Preguntas abiertas para el dueño

1. **Productos que SICAR no conoce.** Un cliente pide algo que nunca se ha
   manejado: ¿basta con darlo de alta en SICAR y agregarlo al día siguiente, o
   hace falta pedirlo el mismo día? Si es lo segundo, esta regla se cae y hace
   falta un renglón sin `producto_id`, que la recepción no sabría emparejar.
2. **Un pedido cancelado de algo agregado a mano**: ¿vuelve solo en la
   siguiente lista (lo que propone la regla 4), o se da por perdido? Volver es
   un clic de descartar si ya no hace falta; perderse es un cliente que se
   quedó esperando.
