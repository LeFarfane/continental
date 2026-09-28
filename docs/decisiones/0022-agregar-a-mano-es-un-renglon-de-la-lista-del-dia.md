# 0022 — Agregar a mano lo que no se vendió es un renglón más de la lista del día

**Fecha:** 2026-09-28  ·  **Estado:** propuesta — no se construye antes del
primer día real de operación del Pedido. Sus dos preguntas las contestó el
dueño el mismo día: la primera cambió la regla 1, la segunda confirmó la 4
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

Y un hecho de SICAR, dicho por el dueño el 2026-09-28: **un producto nuevo
solo se da de alta con su factura en la mano**, y el alta y la compra se
capturan juntas, con la cantidad que llegó. O sea que un producto que nunca se
ha manejado **no existe en SICAR hasta que llega**.
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

1. **Un producto que SICAR todavía no conoce entra por su código de barras.**
   Como el alta solo se hace con la factura (arriba), pedir primero y dar de
   alta después es el único orden posible. Ese renglón lleva `producto_id`
   vacío, la clave EAN de 13 dígitos y la descripción tal como las mostró un
   portal en Buscar (NADRO y LEVIC enseñan el EAN; un resultado que solo trae
   código interno no se puede agregar así). **La recepción lo encuentra por esa
   clave**: la noche en que la cadena trae el alta, trae también su compra, y
   el producto nuevo de `dim_producto` con ese EAN lleva a ella —una noche de
   retraso, la de siempre—. Al confirmarse la recepción, el renglón gana su
   `producto_id` y desde ahí es un renglón como cualquiera. Un producto que sí
   está en SICAR entra por su `producto_id`, como estaba propuesto.
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
   sus piezas, sumadas a la siguiente lista (confirmado por el dueño el
   2026-09-28, pregunta 2). Lo que llegó
   de menos ya funciona sin tocar nada: son las piezas que faltaron.
5. **Cerrar sin pedirlo avisa que se pierde**, igual que lo que faltó de un
   parcial: entra a `cierre.lo_que_se_perderia`. No pasa a la lista
   siguiente.

Se agrega desde dos lugares, con una sola ruta detrás
(`POST /api/pedido-sugerido/{id}/renglon`, `{producto_id o clave, cantidad}`):
desde la pestaña **Pedido**, con el código de barras; y desde un resultado de
**Buscar**: si es nuestro, por su `producto_id`; si no, por el EAN que mostró
el portal.

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
  propuesta cero y cantidad final". Y por la regla 1, `producto_id` pasa a
  admitir nulos **solo** en un renglón agregado a mano con clave de 13 dígitos
  (un CHECK), con un índice único parcial `(pedido_sugerido_id, clave) where
  producto_id is null` que hace por esos renglones lo que `ux_renglon_producto`
  hace por los demás. `verificar_rol.sql` gana sus comprobaciones.
- **La recepción aprende a buscar por clave.** Hoy empareja por `producto_id`
  (ADR 0014); para el renglón sin él, pasa primero por `dim_producto` con el
  EAN. Todo lo demás que se ancla en `producto_id` —la memoria de lo pedido
  (ADR 0012), lo que faltó (ADR 0015)— empieza a valer para ese renglón en
  cuanto la recepción le pone su `producto_id`.
- **La pantalla lo marca**: "agregado a mano por …" en el lugar donde un
  renglón vendido dice su ventana de ventas; sin ventas, los días de cobertura
  no existen y se dice así, no con un cero. La vista "Todo lo vendido" deja de
  ser exacta y habrá que renombrarla.
- **La conciliación (ADR 0021) cuenta estos renglones aparte.** Mide qué tan
  bien propone el sistema; lo que agregó una persona no es una propuesta
  acertada ni fallida.
- **Lo que no se construye con esto**: el margen o el precio de venta (eso es
  el puente), un producto nuevo que ningún portal enseña con su EAN, y agregar
  desde Vigilancia (el aviso manda a Buscar, y de Buscar se agrega).

## Preguntas para el dueño

1. ~~**Productos que SICAR no conoce.** ¿Basta con darlo de alta en SICAR y
   agregarlo al día siguiente?~~ **Contestada el 2026-09-28: no se puede.** El
   alta necesita la factura, y la factura llega con el producto. De ahí sale
   la regla 1 como está arriba. La primera versión de este ADR decía que un
   renglón sin `producto_id` "la recepción no sabría emparejar"; con el alta y
   la compra capturadas juntas, sí sabe: por la clave, una noche después.
2. ~~**Un pedido cancelado de algo agregado a mano**: ¿vuelve solo en la
   siguiente lista, o se da por perdido?~~ **Contestada el 2026-09-28: vuelve
   en la siguiente lista.** Es la regla 4 como estaba propuesta: si ya no hace
   falta, se descarta con un clic; perderse era un cliente esperando.
