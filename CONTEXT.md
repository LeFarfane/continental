# Glosario de Continental

El lenguaje del negocio, no el del código. Si un término de aquí y el código no
coinciden, uno de los dos está mal y hay que arreglarlo, no convivir con los dos.

Esto es un glosario y nada más: no lleva decisiones de arquitectura (esas van a
`docs/decisiones/`), ni estado del proyecto (ese va a `HANDOVER.md`), ni cómo se
instala nada.

## Las personas

**Dueño** — quien decide qué se compra y a quién. Ve todo.

**Encargado** — quien atiende el mostrador y arma los pedidos del día. Ve lo
mismo que el dueño: la diferencia entre los dos es de quién firma cada acción,
no de qué puede hacer.

**Negocio** — una farmacia concreta. Hoy hay una. Todo lo que Continental
guarda dice a qué negocio pertenece, aunque hoy siempre sea el mismo.

## Lo que se compra y a quién

**Proveedor** — un mayorista al que la farmacia le compra y donde tiene cuenta:
NADRO, LEVIC, VICMA, QuePharma. Tienen precio de compra.

**Cadena** — una farmacia competidora cuyo precio de mostrador se mira para
saber si estamos caros: Guadalajara, Similares, del Ahorro, Benavides, San
Pablo. No tienen relación con nosotros y publican precio al público.

> Proveedor y cadena nunca son lo mismo. El precio de un proveedor es lo que
> pagamos; el de una cadena es lo que cobra alguien más. Compararlos entre sí no
> significa nada.

**Producto** — un artículo del catálogo de la farmacia.

**Clave** — el código de barras del producto (EAN de 13 dígitos). Es lo único
que significa lo mismo en nuestro catálogo y en el de un proveedor, y por eso es
lo único con lo que se empareja un producto nuestro con el suyo.

## El pedido

**Pedido sugerido** — la lista de un día: qué conviene comprar, armada por el
sistema a partir de lo que se vendió. No se le envía a nadie.

- `abierto` — todavía se está trabajando.
- `cerrado` — ya se pidió lo que se iba a pedir.
- `vencido` — pasó su día y quedaron renglones sin atender.

**Renglón** — un producto con su cantidad dentro de un pedido sugerido.

- `abierto` — está propuesto y nadie lo ha atendido.
- `en tránsito` — ya se le pidió a un proveedor y todavía no llega. **No se
  vuelve a proponer mientras esté así**, porque eso sería pedirlo dos veces.
- `recibido` — llegó completo.
- `recibido parcial` — llegó menos de lo pedido. Lo que faltó vuelve a
  proponerse.
- `descartado` — una persona decidió no pedirlo.

**Pedido** — lo que se le pide a **un** proveedor: nace de renglones de un
pedido sugerido. Un pedido sugerido puede repartirse en varios pedidos, uno por
proveedor.

- `borrador` — se está armando. Todavía **no se le pidió a nadie**, así que se
  puede cambiar: mover un renglón a otro proveedor, corregir una cantidad,
  volver a repartir.

> Un renglón que entra en un pedido en `borrador` **sigue `abierto`**, no pasa
> a `en tránsito`. `en tránsito` quiere decir "ya se le pidió a un proveedor", y
> un borrador no se le ha pedido a nadie.

**Probablemente recibido** — apareció una compra que encaja con un renglón en
tránsito, pero los datos no alcanzan para afirmar que sea la misma mercancía.
Es una sugerencia que espera confirmación de una persona, nunca un hecho.

**Reposición** — comprar lo que se vendió, pieza por pieza. Es la regla con la
que el sistema propone cantidades; no considera mínimos, máximos ni empaques.

**Días de cobertura** — cuántos días duraría la existencia actual al ritmo al
que se ha vendido. Sirve para ordenar la lista por urgencia, no para decidir si
un producto entra a ella.

## Cómo se clasifica un producto

**Anaquel** — el lugar físico donde vive el producto en la tienda (`PATENTE 1`,
`GENERICO 3`, `BOTICA 2`, `VITRINA 1`, `SUPER`, `CANASTA`…). Es un lugar, no
una etiqueta de catálogo, y por eso se le cree más que a la categoría.

**Medicamento** — para Continental, lo que vive en los anaqueles de patente,
genérico, naturista, botica y vitrina. Es lo que se le compra a un proveedor.

**Botica** — material de curación: vendas, jeringas, sondas. Se le compra a los
mismos proveedores, así que cuenta como medicamento para el pedido.

**Abarrote** — lo que vive en super, canasta o refrigerador. Compite contra la
tienda de la esquina, no contra una farmacia, y no se le compra a un proveedor
de medicamentos.

**Sin clasificar** — un producto que se vendió y no tiene anaquel conocido (688
de 3,429 al 2026-09). **Siempre se muestra, marcado como tal.** Un producto que
desaparece de la lista por no tener anaquel es mercancía que va a faltar sin que
nadie se entere.
