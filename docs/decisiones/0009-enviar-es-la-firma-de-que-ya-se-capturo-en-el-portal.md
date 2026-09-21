# 0009 — Enviar es la firma de que alguien ya lo capturó en el portal, no un envío

**Fecha:** 2026-09-21  ·  **Estado:** aceptada, **enmendada por el 0013** en
un punto: existe `cancelado`, una salida hacia adelante desde `enviado`. Sigue
sin haber "desenviar". Ver la nota al final de "Por qué no hay desenviar".

## Contexto

El ticket 21 es el momento en que un pedido deja de ser un borrador. La palabra
que el glosario y la pantalla usan es **enviar**, y esa palabra tiene un
significado obvio que aquí **es falso**: Continental no le manda nada a ningún
proveedor.

Tres cosas ya escritas lo delimitan, y ninguna se decide en este ticket:

1. **Regla 1 de `CLAUDE.md`:** *Continental no scrapea, no mide y no toca un
   navegador.* El día que aquí aparezca un `import playwright`, la decisión del
   ADR 0001 se rompió.
2. **El ADR 0002 dejó *capturar el pedido en el portal* fuera de alcance**, con
   su razón: los cuatro portales tienen carrito y formas distintas, la sesión se
   cae sola —medido el 2026-09-19: las cuatro caducadas—, y un pedido capturado
   por un robot contra un portal que cambió de HTML es mercancía pedida mal, con
   dinero de verdad.
3. **El correo de Access es una firma y nunca un permiso** (regla 3). Llega
   verificado por Cloudflare en `Cf-Access-Authenticated-User-Email` y sirve para
   saber quién hizo qué.

Entonces, ¿qué es exactamente lo que se guarda al apretar "Enviar"? No es un
hecho que Continental haya observado. Es **lo que una persona declara**: *yo ya
capturé este pedido en el portal de NADRO*. Es un dato de otra naturaleza que
todo lo demás que este módulo guarda —una venta, un precio congelado, una
existencia— y por eso merece su propio ADR: lo que no se decida aquí se va a
decidir solo, mal, la primera vez que alguien lea la palabra "enviado" y suponga
que hubo un envío.

## Opciones consideradas

1. **Continental captura el pedido en el portal** (por Doyle) y marca `enviado`
   cuando el portal acusa. Sería un envío de verdad.
2. **Continental le manda un correo al proveedor** con el pedido, y `enviado`
   quiere decir "el correo salió".
3. **No guardar nada.** La pantalla imprime el pedido, el encargado lo captura
   donde sepa, y el sistema no se entera. Los renglones se cierran con la lista.
4. **`enviado` es una declaración de la persona, firmada**, y la pantalla dice
   con todas sus letras qué significa. *(elegida)*

## Decisión

**La cuarta.** `borrador` → `enviado` lo escribe una persona, se firma con el
correo que verificó Access (`enviado_por`, `enviado_en`) y significa
exactamente *"yo ya lo capturé en el portal del proveedor"*. Continental no
manda nada a nadie y la pantalla lo dice en el mismo bloque donde está el botón,
no en una nota al pie.

De ahí salen cinco reglas concretas:

- **El total en pesos se ve antes de apretar**, dentro del botón y al lado del
  pedido. Es lo que se va a comprometer.
- **Y tiene que ser el de ahora**: un pedido cuyo total envejeció no se envía,
  se manda a volver a partir.
- **Un pedido `enviado` ya no se edita**, y eso lo sostiene el `WHERE` de cada
  sentencia, no un `if` de la pantalla.
- **Al enviar, sus renglones pasan a `en tránsito`** —"ya se le pidió a un
  proveedor y todavía no llega" (`CONTEXT.md`)—, que es lo que impide volver a
  proponerlos mañana.
- **No hay "desenviar"** desde la pantalla.

## Razones

### Por qué no la 1 (capturar en el portal)

Está fuera de alcance por el ADR 0002 y prohibida por la regla 1, y las dos
tienen la misma razón de fondo: **el error aquí cuesta dinero real**. Un precio
mal leído se ve en la pantalla y alguien lo corrige; un pedido mal capturado
llega en cajas. Los cuatro portales tienen carrito distinto, las sesiones se
caen solas y Doyle todavía ni siquiera puede traer un precio real (hilo abierto
1 de `HANDOVER.md`: las cuatro sesiones caducadas el 2026-09-19).

Si algún día se reabre, este ADR no estorba: lo que hoy escribe la persona lo
escribiría el robot, en la misma columna, y `enviado_por` diría quién lo mandó
a hacer. La firma sigue siendo la respuesta a "¿a quién le pregunto qué se
capturó?".

### Por qué no la 2 (un correo)

Suena inocente y es la peor de las cuatro. La farmacia **no hace pedidos por
correo**: tiene cuenta en los cuatro portales y eso es lo que el proveedor
atiende. Un correo no crea un pedido en NADRO; crearía la ilusión de haberlo
hecho, y `enviado` significaría "salió un correo que quizá nadie lee". Además
estrenaría un borde de salida —SMTP, credenciales, rebotes— en un módulo cuya
regla 2 dice que **Continental es la única puerta al exterior** y que hasta hoy
solo habla con Doyle, con Marlowe y con su propio Postgres.

### Por qué no la 3 (no guardar nada)

Porque es exactamente lo que el ticket viene a evitar: *marcarlo como enviado es
lo que después evita pedir doble*. Sin este estado, el renglón se queda
`abierto`, el sugerido de mañana lo vuelve a proponer —la reposición acumula
desde el último cierre— y la farmacia compra dos veces la misma mercancía. El
glosario ya tenía el estado que lo impide (`en tránsito`, *"no se vuelve a
proponer mientras esté así"*) y **nada lo escribía**: el ticket 20 dejó dicho
que repartir un renglón no lo pone en tránsito, porque un borrador no se le ha
pedido a nadie. Esto es lo que lo pone.

### Por qué la firma y no un acuse

Un acuse es la respuesta de alguien más. Aquí no hay alguien más: el hecho
ocurrió en otra pantalla, con otras credenciales, y Continental no lo vio. Lo
único verdadero que se puede guardar es **quién lo dice y cuándo lo dijo**, y
eso es una firma (regla 3). Guardarlo sin firma sería escribir *"se envió"* en
voz pasiva, sin nadie detrás, sobre un hecho que nadie observó — y cuando
después no cuadre la factura no habría a quién preguntarle qué se capturó.

Las dos columnas van **pareadas por un CHECK** (`ck_pedido_envio`), igual que
`ck_renglon_descarte`, `ck_renglon_ajuste` y `ck_renglon_eleccion`: o están las
dos con el estado `enviado`, o no está ninguna. Sin la mitad de ida, un pedido
enviado no diría quién; sin la de vuelta, una firma colgada de un borrador diría
que alguien envió lo que nadie envió.

### Por qué no se puede enviar un pedido vacío

Un pedido que se quedó sin renglones existe —el rol no tiene `DELETE`— y su
total es `NULL`, no cero (ticket 20). Marcarlo `enviado` diría *"capturé esto en
el portal"* sobre nada, y peor: sus renglones ya se fueron a otro pedido, así
que ni siquiera hay qué pasar a `en tránsito`. Se niega en el `WHERE`, con un
`EXISTS` sobre sus renglones, y la pantalla lo explica.

### Por qué NO se puede enviar un pedido con el total viejo

Y esto es lo tercero que se parece a los dos anteriores sin serlo.
`pedido.total_sin_iva` solo se reescribe al partir, así que corregir la cantidad
de un renglón **que ya está dentro** de un pedido lo deja enseñando lo que
costaba hace un rato (hilo abierto 13 de `HANDOVER.md`, que le dejó este caso a
este ticket). Esa cifra es la que alguien va a comparar contra la factura del
proveedor: si no cuadra, nadie sabe si falta mercancía o si el número estaba
rancio.

Había dos salidas y se eligió la segunda:

1. **Recalcular el total al enviar.** Era lo que el hilo proponía y es una
   línea. Se descartó por una razón que no estaba en el hilo: **cambiaría el
   número después de que el encargado leyó el del botón**. Se enviaría un total
   que nadie vio, que es peor que enseñar uno viejo.
2. **Negarse**, con el motivo escrito antes del clic y mandando a "Volver a
   partir" — un botón que ya existe, cuesta un clic y deja el total y su
   `armado_en` coherentes. *(elegida)*

La garantía vive en el `WHERE` de `_ENVIAR_EL_PEDIDO`, con un `NOT EXISTS`
contra los renglones cuyo `ajustada_en` es posterior a `armado_en`. Lo que la
pantalla hace es decirlo antes.

**Lo que queda fuera, dicho:** el total también envejece si llega un **precio**
nuevo después de armar el pedido, y eso no se revisa. Duele mucho menos —la
cantidad es lo que se captura en el portal, y el precio de allá manda sobre el
de Doyle— y revisarlo pediría comparar `armado_en` contra el `consultado_en` de
cada lectura. Condición de disparo: si un total no cuadra contra una factura y
la cantidad estaba bien.

### Por qué SÍ se puede enviar un pedido sin total

Y esto es lo contrario del caso anterior, aunque se parezcan. Un pedido con
alguna línea sin precio tiene `total_sin_iva = NULL` y **sí se puede enviar**:
la quinta casilla del ticket 20 dice que *un renglón sin precio de ese proveedor
se puede pedir igual*, y el encargado ve el precio de verdad en el portal
mientras lo captura. Negar el envío aquí volvería el precio de Doyle un requisito
para operar, que es justo lo que la regla 4 evita —"sin dato" nunca es un cero,
y tampoco es un bloqueo—.

Lo que sí hace la pantalla es **decirlo antes**: el botón escribe "total sin
saber" en vez de una cifra, y al lado va cuántas líneas van sin precio y cuánto
suma lo que sí se sabe.

### Por qué enviar NO exige que la lista siga `abierta`

Todas las demás operaciones del módulo sí lo exigen —descartar, devolver,
corregir la cantidad, elegir proveedor, partir— porque una lista `cerrada`
quiere decir *"ya se pidió lo que se iba a pedir"* y cambiarla después separaría
el renglón de lo que de verdad se le pidió al proveedor.

**Enviar es lo contrario de eso: es decir que sí se pidió.** Si además exigiera
la lista abierta, un encargado que cierra la lista antes de marcar el último
pedido se quedaría con renglones `abierto` dentro de una lista cerrada **y sin
manera de moverlos a `en tránsito`** — o sea, con mercancía pedida que el
sistema va a volver a proponer y que la recepción (ticket 26) no va a poder
cruzar. Se decidió que la condición sea **la del pedido y solo la del pedido**:
`estado = 'borrador'`.

Lo que se renuncia, dicho: se puede marcar como enviado un pedido de una lista
`vencida`. Es lo correcto —el pedido se capturó, pasara lo que pasara con la
lista— y es además el único camino que deja esos renglones en un estado que la
recepción sepa leer.

### Por qué no hay "desenviar"

Porque no hay nada que deshacer de este lado: la mercancía ya está pedida en el
portal del proveedor, y un botón aquí no la despide. Un "volver a borrador"
serviría para exactamente un caso —alguien apretó Enviar por error antes de
capturar— y a cambio abriría el camino a editar un pedido que sí está en el
portal, que es lo que la tercera casilla del ticket viene a impedir.

El caso del error se atiende donde se puede atender de verdad: con credenciales
de dueño, con el `UPDATE` que `continental.verificar` ya imprime como comando de
reparación de su invariante 3. Es a propósito que cueste: quien lo corre sabe lo
que está diciendo.

> **Enmienda del ADR 0013 (ticket 25, 2026-09-21).** Lo de arriba sigue en pie:
> **no hay "desenviar"**, un pedido enviado no vuelve a `borrador` ni se edita.
> Lo que el 0013 agrega es **`cancelado`**: una salida *hacia adelante* desde
> `enviado`, terminal y firmada (`cancelado_por`, `cancelado_en`), que quiere
> decir *"este pedido no está en el portal: nunca se capturó, o se canceló
> allá"*. No abre el camino que este ADR temía —editar lo capturado— porque un
> cancelado no se edita, no se vuelve a enviar y no se descancela; sus renglones
> pasan a `cancelado` y lo que vuelve es su producto, en la siguiente lista. El
> caso del error de dedo que aquí se mandaba al `UPDATE` de dueño ahora tiene
> botón. Y `ck_pedido_estado` pasa a tres valores, con `ck_pedido_envio`
> exigiendo la firma del envío también en un cancelado.

## Consecuencias

- **`ck_pedido_estado` se amplía a `('borrador', 'enviado')`**, con su migración
  `sql/migraciones/0006-enviar-el-pedido.sql` y lo mismo dentro de
  `sql/crear_tablas.sql` para una base desde cero. Es el precio que el ticket 20
  dejó anotado con todas sus letras al no adelantar el nombre.
- **`pedidos.pedido` gana dos columnas**, `enviado_por` y `enviado_en`, con
  `ck_pedido_envio` pareándolas contra el estado. **No estrena tabla**, así que
  `sql/crear_rol.sql` no hace falta volver a correrlo: el `GRANT SELECT, INSERT,
  UPDATE` es sobre la tabla entera y no se usan permisos por columna.
- **El invariante 3 de `continental.verificar` se enciende solo.** Estaba
  escrito desde el ticket 17 esperando estas dos columnas con **estos nombres**,
  y por eso `COLUMNAS_QUE_EXIGE_EL_ENVIO` no cambia: deja de imprimirse como
  PENDIENTE en cada despliegue y empieza a revisar de verdad.
- **Un renglón `en tránsito` deja de contar como trabajo pendiente.** Deja de
  entrar en la partición, en el conteo de huecos, en la cola del botón de
  completar y en el aviso de sesiones caducadas. Antes de este ticket ningún
  código escribía ese estado, así que ninguna de esas cuentas lo había visto
  nunca; a partir de aquí, contarlo sería mandar a consultar cuatro portales por
  mercancía que ya se pidió.
- **El hilo abierto 13 de `HANDOVER.md` se cierra aquí**, con la otra de sus
  dos opciones: enviar un pedido cuyo total envejeció se niega, en vez de
  recalcularlo en silencio.
- **Lo que este ADR no decide:** qué pasa cuando la mercancía llega. Eso es el
  ticket 26 y sus dos estados de recepción, que ya están en el glosario.
