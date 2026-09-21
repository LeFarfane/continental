# 0013 — Cancelar suelta el tránsito sin desenviarlo, y lo que vuelve es el producto, no el renglón

**Fecha:** 2026-09-21  ·  **Estado:** aceptada  ·  **Enmienda:** el ADR 0009 en
un punto (abajo, "Qué cambia del 0009")

## Contexto

Desde el ticket 24 un renglón `en tránsito` **no se vuelve a proponer** (ADR
0012). Es lo que impide pedir dos veces, y tiene un revés: si el renglón nunca
llega, se queda fuera de la lista **para siempre**. Nada lo saca de ahí —la
recepción (ticket 26) todavía no existe, y aunque existiera, lo que no llega no
se recibe—. Es mercancía que va a faltar sin que nadie lo note, que es la falla
que la regla 4 prohíbe.

El ticket 25 pide la válvula de escape, en cuatro casillas: señalar lo que lleva
más de N días en tránsito, **cancelar un pedido que nunca se capturó** con sus
renglones "de vuelta a `abierto` para el siguiente sugerido", que cancelar quede
firmado, y **devolver a la lista** un renglón atrasado uno por uno.

Tres cosas ya escritas chocaban con eso, y ninguna se podía resolver por
accidente:

1. **El ADR 0009 dijo que no hay "desenviar"**: *"un 'volver a borrador'
   serviría para exactamente un caso —alguien apretó Enviar por error antes de
   capturar— y a cambio abriría el camino a editar un pedido que sí está en el
   portal"*. Y `almacenamiento.ESTADOS_DEL_PEDIDO` decía, con todas sus letras,
   que no había estado `cancelado` porque nadie lo había pedido. Este ticket lo
   pide.
2. **"Vencido" ya es un estado del pedido sugerido** (`CONTEXT.md`: *pasó su día
   y quedaron renglones sin atender*). Un "tránsito vencido" es otra cosa, de
   otro objeto.
3. **El ticket 24 dejó dicho que cancelar es otra regla**: al recibirse, lo que
   vuelve es lo vendido *después* del ancla; al cancelarse vuelve **también lo
   que el renglón cubría**, porque nunca se pidió.

Y una cuarta que el ticket escribía sin notarla: *"vuelven a `abierto` para el
siguiente sugerido"*. La lista de un renglón en tránsito casi siempre es vieja
—cerrada o vencida— y el glosario dice que **solo una lista `abierta` se deja
modificar**.

## Opciones consideradas

**Qué es cancelar:**

1. **Volver a `borrador`** —el "desenviar" que el 0009 negó—: el pedido se
   reabre y se edita.
2. **Un estado nuevo del pedido, `cancelado`, terminal** —ni se edita, ni se
   vuelve a enviar, ni se descancela—, firmado como el envío. *(elegida)*
3. **Nada en el pedido**: cancelar es devolver cada renglón, uno por uno.

**Adónde va el renglón cancelado:**

A. **De vuelta a `abierto`, en su lista vieja**, como dice el ticket.
B. **A `abierto` si su lista sigue abierta, y a otra cosa si no.**
C. **A un estado nuevo, `cancelado`, siempre; y lo que vuelve es su
   producto, en la siguiente lista**, con todo lo que cubría. *(elegida)*

**Qué es "tránsito vencido":**

i. **Un estado del renglón** (`vencido`, o `atrasado`), escrito por alguien.
ii. **Una señal calculada** cada vez que se mira, que no se guarda, **y con
    otro nombre: atrasado**. *(elegida)*

## Decisión

**2 + C + ii.**

- El pedido gana el estado **`cancelado`**, solo desde `enviado`, firmado con
  `cancelado_por` y `cancelado_en`. Quiere decir exactamente *"este pedido no
  está en el portal del proveedor: nunca se capturó, o se canceló allá"*. Es una
  **declaración**, igual que enviar, y por las mismas razones del 0009 lleva
  firma y no acuse. **Continental no cancela nada en ningún portal**, igual que
  no captura nada en ninguno, y la pantalla lo dice junto al botón.
- El renglón gana el estado **`cancelado`** —*se dejó de esperar sin haber
  llegado*—, con la misma firma. Lo escriben dos caminos: cancelar el pedido
  (sus renglones en tránsito, en la misma transacción y con el mismo instante)
  y **devolver a la lista** un renglón atrasado, él solo, con su pedido todavía
  `enviado`.
- **El renglón cancelado no vuelve a `abierto`.** Lo que vuelve es **su
  producto, en la siguiente lista que se arme**, contado **desde el principio de
  lo que ese renglón cubría**: su `ventas_desde` si tenía ventana propia, y si
  no el principio de la ventana de su lista. Lo lleva la memoria del ticket 24
  —`lo_ya_pedido` trae lo cancelado que nadie ha atendido, y
  `LoYaPedido.retiene_desde` dice desde cuándo—, así que ninguna tabla nueva y
  ninguna venta copiada.
- **Atrasado** es lo que lleva **más** de N días en camino, N en
  `config/continental.yml` (`pedido.dias_en_transito_para_atrasado: 7`),
  contados en días de calendario de la farmacia. No es un estado ni una columna:
  se calcula al mirar. Devolver a la lista **solo se puede con lo atrasado**, y
  eso lo sostiene el `WHERE` de `_DEVOLVER_EL_ATRASADO` con un límite que viaja
  como parámetro.

## Razones

### Por qué no la 1 (volver a `borrador`)

Por lo mismo que el 0009, que sigue teniendo razón: un borrador se edita, y un
pedido que alguien sí capturó en el portal no se puede editar desde aquí sin que
lo de aquí y lo de allá dejen de coincidir. Y además no serviría: el renglón
vuelto a `abierto` dentro de una lista cerrada no se puede repartir (la lista no
se modifica), así que el pedido reabierto quedaría con renglones que ya no se
pueden mover a ningún lado.

### Por qué no la 3 (solo devolver renglones)

Porque "este pedido nunca se capturó" es un hecho **del pedido**, y quien lo
descubre lo descubre de una vez. Obligar a devolver renglón por renglón —y solo
los atrasados— dejaría el caso de todos los días sin salida: *apreté Enviar por
error hace diez minutos*. Y el pedido se quedaría diciendo `enviado` sobre algo
que nadie capturó, con una firma que afirma lo que no pasó.

### Por qué no la A (de vuelta a `abierto` en su lista vieja)

Es lo que el ticket decía, y es la que rompe más cosas:

- **La lista vieja casi siempre está cerrada o vencida.** El glosario dice que
  solo una lista `abierta` se deja modificar (unificado el 2026-09-20). Un
  `abierto` dentro de una lista cerrada es trabajo pendiente en algo que dice
  *"ya se pidió lo que se iba a pedir"*: no se puede descartar, ni corregir, ni
  repartir.
- **Nadie lo volvería a proponer.** La siguiente lista acumula desde el corte
  del último cierre; los días de ese renglón ya quedaron atrás del corte. Un
  `abierto` en una lista cerrada es exactamente lo que el ticket 09 da por
  atendido: sus ventas **se perderían**, que es lo contrario de lo que el
  ticket pide.
- **Y en la lista de hoy tampoco sirve**: el pedido de ese proveedor en esta
  lista ya existe (`ux_pedido_proveedor`: uno por proveedor por lista), así que
  volver a partir no podría meter el renglón en un pedido nuevo a NADRO sin
  reabrir el cancelado. Eso es desenviar por la puerta de atrás.

### Por qué no la B (depende de la lista)

Porque serían dos reglas donde el ticket 24 dejó una, y las dos se equivocarían
en los bordes: "¿la lista de hoy o la de ayer que nadie ha vencido?". La C tiene
una sola respuesta para todos los casos, la misma que el 0012 ya dio para lo
recibido: **lo que se muestra es lo guardado y no se recalcula; lo que vuelve,
vuelve en la siguiente lista**. Quien canceló por error esta mañana ve el
renglón marcado —*"vuelve a proponerse en la siguiente lista, no en ésta"*— y
mañana lo tiene de vuelta con todo lo suyo.

Lo que se renuncia, dicho: **quien cancela un pedido de hoy no puede volver a
pedirlo hoy desde esta pantalla**. Tiene que esperar a la siguiente lista, o
capturarlo en el portal por fuera —y entonces la advertencia de la quinta
casilla del ticket 24 aplica: lo capturado por fuera se propone otra vez—.
Condición de revisión: si el encargado se encuentra seguido en ese caso, lo que
hace falta es una acción "volver a pedir a otro proveedor" sobre el renglón
cancelado de hoy, no reabrir el pedido.

### Por qué desde el principio de lo que cubría, y por qué no se duplica

El ticket 24 recuerda el **ancla** —hasta qué día repuso el pedido— y, al
recibirse, cuenta desde el día siguiente. Un renglón cancelado **no repuso
nada**: sus ventas nunca se pidieron. Así que su producto se cuenta desde el
principio de su propia ventana —la `ventas_desde` del renglón si la tenía (ya
traía lo de un pedido anterior), o el principio de la ventana de su lista—.

No se propone dos veces por tres cosas que ya estaban y una que se agrega:

- **Un solo intervalo por producto** (`MemoriaDeLoPedido.recortar`): si la
  ventana de la lista nueva ya cubre esos días —la lista vieja no se cerró—, el
  intervalo propio los abarca en vez de sumarlos.
- **Se olvida en cuanto se atiende**, con el mismo `NOT EXISTS` que lo
  recibido: una lista posterior **cerrada** que trae el producto ya propuso esas
  ventas.
- **Se olvida si el producto se vuelve a pedir** —o se vuelve a cancelar—: ese
  renglón de después se armó con la memoria, así que ya carga con lo pendiente
  en su `ventas_desde`.
- **Lo que viene en camino le gana**: cancelado y vuelto a pedir, el producto
  sigue fuera mientras el pedido nuevo no llegue.

Los escenarios de varios días que lo fijan están en `tests/test_cancelar.py`:
con las listas de en medio cerradas, sin cerrar, el mismo día, y una devolución
a las dos semanas —3 que cubría + 4 de la semana + 1 + 1 = 9, y al día
siguiente 1—.

### Por qué atrasado es una señal y no un estado

Porque **cambia solo, con el paso del tiempo**, sin que nadie haga nada. Una
columna que dijera "atrasado" la tendría que escribir alguien —¿un proceso de
noche?— y envejecería entre una escritura y otra, que es la misma razón por la
que la sugerencia de proveedor no se guarda (ticket 20). Calculada, está bien
cada vez que se mira.

Y **no se llama "vencido"**: `vencido` es un estado de la **lista**, y un
renglón "vencido" dentro de una lista "abierta" —o al revés— se leería como la
misma cosa dicha dos veces. "Atrasado" es la palabra del mostrador para un
pedido que no llegó cuando debía.

### Por qué el límite viaja como parámetro y no como aritmética en SQL

Para que la pantalla y la base no puedan separarse. La pantalla decide qué
ofrecer con `transito.dias_en_transito` y la base decide qué acepta con
`p.enviado_en < :enviado_antes_de`, calculado por `transito.enviado_antes_de`
—la medianoche de la farmacia de hace N días— con el mismo `ahora`. Una prueba
recorre doce días de hora en hora con tres umbrales y las dos dicen lo mismo en
cada instante.

Y porque la cuenta en SQL es una trampa: en Postgres `at time zone '-06'` sigue
la convención **POSIX**, y se lee como **UTC+6**. Con un `interval` o con
`current_date` el día se contaría en el reloj del contenedor, que corre en UTC.

### Por qué N es 7 y por qué no hay número de omisión

**No está medido**: hasta el ticket 26 nada se marca como recibido, así que no
hay un solo tiempo de entrega guardado. Siete porque una semana cubre cualquier
combinación de fin de semana y puente sin que el aviso se encienda sobre una
entrega normal; porque **mientras no haya recepción, todo lo que llegó sigue en
tránsito** y a los N días se ve atrasado igual que lo que no llegó —un N chico
invitaría a devolver lo que sí llegó, que es pedirlo dos veces—; y porque a los
siete días la pantalla ya escribe la fecha con los días que lleva.

Al revés que `dias_primera_vez` y los topes del lote, **si el número falta o
está mal escrito, no se inventa uno**: la lectura truena y la pantalla lo
enseña como un hueco con su motivo. Tronar aquí no deja a nadie sin pedido —lo
único que se pierde es la señal— y un número elegido en silencio sería una
válvula que se abre en un día que nadie escogió.

## Qué cambia del 0009

El 0009 decía dos cosas que este ADR toca, y **solo esas dos**:

- *"No hay 'desenviar' desde la pantalla."* **Sigue sin haberlo.** Un pedido
  enviado no vuelve a `borrador`, no se edita, y cancelado no se vuelve a
  enviar ni se descancela. Lo que se agrega es una salida **hacia adelante**:
  `enviado` → `cancelado`, terminal y firmada.
- *"`ck_pedido_estado` se amplía a `('borrador', 'enviado')`"* y la nota del
  código de que no había `cancelado`. Ahora son tres, y `ck_pedido_envio` exige
  la firma del envío también en un pedido cancelado: solo se cancela lo que
  alguien dijo haber enviado, y esa palabra no se borra.

El caso que el 0009 mandaba a arreglar con un `UPDATE` de dueño —*"alguien
apretó Enviar por error"*— ahora tiene botón, porque cancelar **no** abre el
camino que el 0009 temía: no deja editar nada.

## Consecuencias

- **Migración 0009** (`sql/migraciones/0009-cancelar-y-devolver-lo-atrasado.sql`)
  y lo mismo en `sql/crear_tablas.sql`: dos columnas en `pedido`, dos en
  `renglon`, `ck_pedido_estado` y `ck_renglon_estado` con `cancelado`,
  `ck_pedido_envio` ampliado, y dos pares de firma
  (`ck_pedido_cancelacion`, `ck_renglon_cancelacion`). **No crea tabla**:
  `crear_rol.sql` no hace falta volver a correrlo. `verificar_rol.sql` gana
  las comprobaciones 31, 32 y 33. **Va antes del código**: las lecturas de la
  lista nombran las columnas nuevas.
- **Dos rutas**: `POST /api/pedido/{id}/cancelar` y
  `POST /api/renglon/{id}/devolver-atrasado`. Las dos firman con el correo de
  Access —firma y nunca permiso— y la pantalla **vuelve a cargar** después, en
  vez de deducir qué cambió.
- **`ESTADOS_QUE_CIERRAN_EL_TRANSITO` no cambia**: sigue siendo el enganche de
  los tickets 26 y 27 (recibido, recibido parcial). Lo cancelado va en su
  propia tupla y su propia cláusula de `_LO_YA_PEDIDO`, porque vuelve desde otro
  día.
- **Un pedido con algo recibido no se cancela** (el `NOT EXISTS` del `WHERE`):
  si algo llegó, sí se capturó. Hoy nada escribe `recibido`; la condición está
  para que el ticket 26 no tenga que acordarse.
- **Lo que no protege, dicho junto al botón:** Continental no cancela nada en
  el portal. Devolver a la lista algo que el proveedor todavía tiene pedido
  puede traerlo dos veces; y **devolver algo que sí llegó —hoy, que nada se
  marca recibido— lo vuelve a pedir entero**.
- **Condición de revisión.** Cuando el ticket 26 tenga un mes de recepciones,
  medir de `enviado_en` a la recepción y subir N por encima de lo que tardan
  casi todos. Si el botón de devolver se usa sobre cosas que sí llegaron, N está
  bajo.
