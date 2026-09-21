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

> **Solo una lista `abierta` se deja modificar**, y eso vale para las cuatro
> acciones que una persona hace sobre un renglón: descartarlo, devolverlo a la
> lista, corregir su cantidad y elegir a quién se le pide. `cerrado` y `vencido`
> significan que lo que se iba a pedir ya se pidió —o que su día pasó—, así que
> un cambio posterior separaría el renglón de lo que de verdad se le pidió al
> proveedor, y la recepción (ticket 26) se haría contra un renglón que dice otra
> cosa.
>
> Unificado el **2026-09-20**. Hasta ese día descartar era la excepción: se
> dejaba hacer con la lista cerrada porque el ticket 10 nunca pidió lo
> contrario. No era un incumplimiento, era una incoherencia — y de cara al
> encargado, una lista cerrada que todavía se deja modificar es una lista que no
> está cerrada.

**Renglón** — un producto con su cantidad dentro de un pedido sugerido.

- `abierto` — está propuesto y nadie lo ha atendido.
- `en tránsito` — ya se le pidió a un proveedor y todavía no llega. **No se
  vuelve a proponer mientras esté así**, porque eso sería pedirlo dos veces.
  Se ve igual en la pantalla, atenuado y con cuándo se pidió y a quién.
- `recibido` — llegó completo: **al menos** las piezas pedidas. Lo dice
  **una persona**, con su firma: nunca pasa solo (ver *probablemente
  recibido*). Más de lo pedido también es `recibido`, y lo que sobra no se
  descuenta de ninguna lista.
- `recibido parcial` — llegó menos de lo pedido. Lo que faltó vuelve a
  proponerse. Lleva la misma firma, y dice **cuántas llegaron**: de ahí sale
  cuánto faltó.
- `descartado` — una persona decidió no pedirlo.
- `cancelado` — se dejó de esperar sin haber llegado: su pedido se canceló, o
  una persona lo devolvió a la lista porque se atrasó. Lleva firma. **No vuelve
  a `abierto`**: lo que vuelve es su producto, en la siguiente lista.

> **Lo que se vende mientras un renglón está `en tránsito` no se pierde.** El
> producto no se propone, pero sus ventas se siguen contando, y **cuando el
> renglón pasa a `recibido` o `recibido parcial`** la siguiente lista las trae
> — aunque las listas de en medio se hayan cerrado. El renglón que vuelve dice
> desde qué día cuenta. Ver el ADR 0012.
>
> **Y solo sabe de lo que pasó por Continental.** Un pedido que se capturó en
> un portal sin marcarlo aquí como enviado no está `en tránsito`, y su
> mercancía se va a proponer otra vez.

> **Lo que faltó vuelve como piezas, no como ventas** (ticket 27). Pedí 10,
> llegaron 6: la siguiente lista **suma 4** a lo que proponga del producto,
> aparte de lo vendido mientras venía. No se sabe *qué días* se vendieron esas
> 4 —solo que se vendieron y no se repusieron—, así que se dicen en el
> renglón: *"trae también 4 piezas que faltaron en un pedido anterior"*. Un
> producto que faltó entra a la lista aunque no se haya vuelto a vender. Ver
> el ADR 0015.

**Recibir a mano** — decir **cuántas piezas llegaron, en total**, de un renglón
en camino, sin propuesta del sistema. Es la única salida de lo que nunca va a
tener propuesta y la del pedido que llega en dos facturas. Lleva firma —quién y
cuándo— y no lleva compra de SICAR. La misma pregunta **corrige** la cifra de lo
ya recibido —la segunda factura, un error de captura— mientras lo que faltó no
lo haya atendido una lista posterior. Cero no es recibir: si no llegó nada, el
renglón sigue en camino.

> **Lo `cancelado` vuelve entero, y vuelve en la siguiente lista.** Un renglón
> que se dejó de esperar nunca repuso nada, así que su producto se cuenta
> **desde el principio de lo que ese renglón cubría** —no desde el día siguiente
> al ancla, como lo recibido—. Y no vuelve a `abierto` en su lista, que casi
> siempre está cerrada: **solo una lista `abierta` se deja modificar**. En la
> lista de hoy se ve marcado —*"vuelve a proponerse en la siguiente lista, no
> en ésta"*—. Ver el ADR 0013. Si traía piezas que faltaron de antes, vuelven
> con él.

**Atrasado** — un renglón `en tránsito` que lleva **más** de N días en camino,
contados en días de calendario de la farmacia; N está en
`config/continental.yml`. **No es un estado**: se calcula cada vez que se mira,
contra la hora en que se envió, y no se guarda. Lo atrasado se señala con sus
días a la vista y **se puede devolver a la lista** uno por uno, sin cancelar su
pedido: pasa a `cancelado`.

> **Atrasado no es vencido.** `vencido` es de la **lista** —pasó su día y
> quedaron renglones sin atender—; atrasado es de un **renglón en tránsito**. Por
> eso tienen nombres distintos: una lista vencida con un renglón atrasado son
> dos hechos sobre dos cosas.
>
> **Lo que llegó sin dejar compra en SICAR también se ve atrasado.** Desde el
> ticket 26, lo que llega con su compra se propone como *probablemente
> recibido*, y mientras tenga propuesta no se ofrece devolverlo. Pero un pedido
> a un proveedor que SICAR no conoce, o un producto que nunca aparece en
> compras, no tiene con qué proponerse: sigue en tránsito aunque haya llegado,
> y devolverlo a la lista es volverlo a pedir entero. **Desde el ticket 27 su
> salida es recibirlo a mano**, antes de que se atrase.

**Pedido** — lo que se le pide a **un** proveedor: nace de renglones de un
pedido sugerido. Un pedido sugerido puede repartirse en varios pedidos, uno por
proveedor.

- `borrador` — se está armando. Todavía **no se le pidió a nadie**, así que se
  puede cambiar: mover un renglón a otro proveedor, corregir una cantidad,
  volver a repartir.
- `enviado` — **una persona ya lo capturó en el portal del proveedor**. Deja de
  poder cambiarse y sus renglones pasan a `en tránsito`.
- `cancelado` — **una persona dijo que no está en el portal del proveedor**:
  nunca se capturó, o se canceló allá. Solo desde `enviado`, con firma. Es un
  final: no se edita, no se vuelve a enviar y no se descancela. Sus renglones en
  tránsito pasan a `cancelado`, y su mercancía vuelve a proponerse en la
  siguiente lista. **Un pedido con algo recibido —completo o parcial— no se
  cancela**: si llegó algo, sí se capturó.
- `recibido` — ya no le queda nada en camino y **todos** sus renglones
  llegaron completos.
- `recibido parcial` — ya no le queda nada en camino, algo llegó, y alguno de
  sus renglones llegó de menos **o se dejó de esperar**.

> **`recibido` y `recibido parcial` del pedido no se guardan: se calculan de
> sus renglones** cada vez que se miran (ADR 0015). Los tres primeros son lo
> que una persona declaró y sí se guardan; estos dos son la suma de lo que
> otras personas declararon renglón por renglón, y una segunda copia se
> separaría de la primera. En la tabla, un pedido que llegó sigue diciendo
> `enviado` —que sigue siendo verdad: alguien lo capturó en el portal—. Si
> nada de él llegó —todo se devolvió por atrasado—, sigue siendo `enviado`.

> **`enviado` no quiere decir que Continental le mandó algo a nadie.**
> Continental no hace pedidos en los portales y no va a hacerlos (ADR 0002): lo
> captura una persona con las credenciales del dueño, y aquí lo que se guarda
> es **su palabra de que ya lo hizo**, con su correo y la hora. Por eso lleva
> firma —`quién` y `cuándo`— y no acuse: no hay nada de qué acusar recibo.
>
> Un pedido `enviado` **no vuelve a `borrador`** desde la pantalla. Lo que ya
> se capturó en el portal no se descaptura con un clic.
>
> **Cancelar no es "desenviar".** Es la salida hacia adelante para lo que nunca
> se capturó (ADR 0013): el pedido no vuelve a `borrador` ni se edita. Y
> Continental no cancela nada en ningún portal, igual que no captura nada en
> ninguno: si allá sigue pedido, allá hay que cancelarlo.

> Un renglón que entra en un pedido en `borrador` **sigue `abierto`**, no pasa
> a `en tránsito`. `en tránsito` quiere decir "ya se le pidió a un proveedor", y
> un borrador no se le ha pedido a nadie. Lo que lo mueve es **enviar**.

**Capturado** (o **tachado**) — un renglón de un pedido en `borrador` que una
persona ya tecleó en el portal de ese proveedor y marcó en la pantalla de
captura. Lleva firma —quién y cuándo— y se puede destachar mientras el pedido
siga en borrador.

> **Capturado no es un estado del renglón.** El renglón sigue `abierto` hasta
> que su pedido se envía: tachar lleva la cuenta de lo que se tecleó en otra
> ventana, no cambia dónde está la mercancía. Y **tachar todo lleva a enviar
> sin ser requisito**: quien capturó el pedido entero en el portal sin ir
> tachando aquí lo envía igual. Si un renglón tachado se mueve a otro
> proveedor, deja de estar capturado — en el portal nuevo nadie lo ha tecleado.

**Probablemente recibido** — apareció una compra que encaja con un renglón en
tránsito, pero los datos no alcanzan para afirmar que sea la misma mercancía.
Es una sugerencia que espera confirmación de una persona, nunca un hecho.

- **Encaja** quiere decir: mismo proveedor (su `pro_id` de SICAR), mismo
  producto, y una compra del mismo día del envío o posterior, contado en días
  de la farmacia. **Nunca por folio**: su significado no está verificado, y se
  enseña solo para buscarlo en la factura.
- **No es un estado del renglón**: se calcula cada vez que se mira. El renglón
  sigue `en tránsito` hasta que una persona decide:
  - **confirmar** — pasa a `recibido`, firmado, con las compras que lo
    sostienen. Solo se puede si la compra trae al menos lo que se pidió.
  - **recibir parcial** — la compra trae **menos** de lo pedido y una persona
    dice que solo llegó eso: pasa a `recibido parcial`, firmado, con esas
    compras, y lo que faltó vuelve a proponerse (ticket 27). Si falta otra
    factura, se espera: cuando aparezca, se suma a la propuesta.
  - **rechazar** — sigue `en tránsito`, y **esa** compra ya no se le vuelve a
    proponer. Una compra distinta, sí.
- **Una compra confirma un solo renglón.** Si encaja con dos pedidos del mismo
  producto, se propone en los dos y cada uno lo dice.
- **Una noche de retraso es normal**: una compra aparece hasta la cadena de la
  noche siguiente a su captura en SICAR.
- **Hay lo que nunca va a tener propuesta**, y se dice: un pedido a un
  proveedor que SICAR no conoce (QuePharma hoy), y un producto que nunca ha
  aparecido en una compra (606 de 3,429 artículos, 17.7%). Su salida es
  **recibirlo a mano**, que existe desde el ticket 27.

> **Probablemente recibido no es recibido.** Lo primero lo dice el sistema con
> la evidencia a la vista; lo segundo lo dice una persona y lleva su firma. Ver
> el ADR 0014.

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
