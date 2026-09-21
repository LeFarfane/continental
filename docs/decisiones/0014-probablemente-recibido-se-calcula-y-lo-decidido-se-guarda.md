# 0014 — "Probablemente recibido" se calcula cada vez; lo que una persona decide se guarda

**Fecha:** 2026-09-21  ·  **Estado:** aceptada

## Contexto

El ADR 0002 decidió que **la recepción se sugiere, no se afirma**: SICAR no
tiene pedidos, una compra se captura ya recibida, `compra.status` solo vale 1 o
-1 (no hay parcial), no está documentado si `compra.fecha` es el día que llegó o
el día que se capturó, y el significado de `folio` no está verificado. Cerrar
renglones solos cerraría algunos en falso, y un renglón cerrado en falso es
mercancía que no se vuelve a pedir.

Hasta el ticket 25, nada escribía `recibido`. Tres cosas colgaban de eso:

1. **Lo retenido del ticket 24 no volvía nunca.** Su enganche
   (`ESTADOS_QUE_CIERRAN_EL_TRANSITO`, ADR 0012) esperaba un estado que nadie
   escribía.
2. **Lo que llegó se veía atrasado** a los N días (ADR 0013), igual que lo que
   no llegó, y devolverlo a la lista era pedirlo dos veces. El 25 lo advertía
   junto al botón.
3. **El `NOT EXISTS` sobre lo recibido** de `_CANCELAR_EL_PEDIDO` estaba puesto
   y nunca se ejercitaba.

El ticket 26 pide siete cosas; cinco decisiones no estaban tomadas en ninguna
parte, y este ADR las toma: qué es "probablemente recibido" (¿un estado o un
cálculo?), qué hacer con las cantidades, qué hacer con una compra que encaja con
dos renglones, qué pasa con el proveedor sin puente, y en qué hora se mide
"posterior al envío".

Cuatro hechos delimitan la solución:

- `marts.fct_compras` tiene grano **compra × artículo** (`unique (compra_id,
  producto_id)`), trae `proveedor_id` (el `pro_id` de SICAR), `fecha_id` —la
  fecha es **un día**, sin hora— y `folio`. El rol `continental` ya la puede
  leer (`crear_rol.sql`, ticket 07) y farmacia-data la otorga desde el
  `config(grants=...)` del modelo.
- **606 de 3,429 artículos (17.7%) nunca aparecen en compras** (medido sobre el
  respaldo del 2026-07-27). Entran por otra vía y no dejan rastro.
- **QuePharma no está en `dim_proveedor`** (ADR 0008): un pedido a QuePharma
  guarda `proveedor_id` en `NULL`, y ninguna compra de SICAR se le puede cruzar.
- `enviado_en` es un **instante** con zona; el contenedor corre en UTC, y en
  Postgres `at time zone '-06'` es la convención POSIX y se lee UTC+6 (lo midió
  el ticket 25).

## Opciones consideradas

**Qué es "probablemente recibido":**

1. **Un estado guardado del renglón** (`probablemente recibido`), escrito cuando
   aparece la compra —por el lote de la noche o por la carga de la pantalla—.
2. **Una propuesta calculada cada vez que se mira**, que no se guarda. Lo que
   se guarda son las dos decisiones de una persona: confirmar y rechazar.
   *(elegida)*

**Cómo se recuerda un rechazo** (solo aplica a la 2):

a. No se recuerda: rechazar no escribe nada.
b. Una **fecha tope** por renglón: las compras de ese día o anteriores ya no se
   proponen.
c. **Qué compras** se rechazaron, por su `compra_id`. *(elegida)*

**Dónde se guarda:**

i. Una tabla de cruce nueva (`pedidos.recepcion`, una fila por renglón y compra).
ii. **Columnas en `pedidos.renglon`**, con `bigint[]` para las compras.
   *(elegida)*

**Qué hacer con las cantidades:**

A. Confirmar siempre, diga lo que diga la compra.
B. **Confirmar solo si la evidencia trae al menos lo pedido**; con menos, se
   enseña y no se ofrece el clic. *(elegida)*
C. Con menos, pasar a `recibido parcial` (es el ticket 27).

**Una compra que encaja con dos renglones** (dos pedidos del mismo producto al
mismo proveedor, los dos en camino):

- Asignarla al más viejo, en silencio.
- **Proponerla en los dos, decirlo en los dos, y que la tabla impida que
  confirme dos.** *(elegida)*
- Repartir sus piezas entre los dos.

## Decisión

**2 + c + ii + B + la segunda de la compra compartida**, y las otras dos
preguntas con una frase cada una:

- **"Probablemente recibido" no es un estado.** `recepcion.proponer` —pura—
  cruza lo que está `en tránsito` (de cualquier lista, **la de hoy incluida**)
  con las compras del almacén **por proveedor (`pro_id`), producto y día
  posterior o igual al del envío, nunca por folio**, y devuelve propuestas con
  su evidencia. El renglón sigue `en tránsito` hasta que una persona:
  - **confirma** → pasa a `recibido`, con `recibido_por`, `recibido_en` y
    `recibido_con_compras` (los `compra_id` que juzgó). Con eso, lo retenido del
    24 vuelve solo: `recibido` está en `ESTADOS_QUE_CIERRAN_EL_TRANSITO`.
  - **rechaza** → **sigue en tránsito** —"rechazar lo devuelve a `en tránsito`"
    es literal: nunca dejó de estarlo—, y esas compras se agregan a
    `compras_rechazadas`, con la firma del último que rechazó. No se le vuelven
    a proponer; una compra distinta, sí.
- **Proveedor sin puente**: nunca habrá propuesta, y la pantalla lo dice con
  esas palabras (`MOTIVO_SIN_PUENTE`).
- **La fecha**: "posterior al envío" se mide en **días de la farmacia** (UTC-6
  fijo), calculado en Python (`recepcion.dia_del_envio`), y **el mismo día
  cuenta**. La lectura de compras recibe ese día como parámetro; ninguna
  aritmética de zonas vive en SQL.

Migración **0010**: seis columnas y cinco CHECK en `pedidos.renglon`. No crea
tabla.

## Razones

### Por qué la propuesta no se guarda

**Porque la evidencia puede desaparecer, y una afirmación guardada no se
entera.** Una compra se cancela en SICAR (`status = -1`, y `fct_compras` la
filtra), o la cadena de una noche no corre y el almacén se queda con lo de
antes. Guardada, la columna seguiría diciendo "probablemente recibido" sobre
algo que ya no tiene evidencia, y nadie podría distinguir esa cifra vieja de una
de hoy. Es la misma razón por la que la sugerencia de proveedor no se guarda
(ticket 20) y por la que "atrasado" no es un estado (ADR 0013): **lo que cambia
solo no se escribe; lo que decide una persona, sí**.

Y porque un estado nuevo rompería lo que ya existe sin avisar. `_LO_YA_PEDIDO`
saca un producto de la lista **porque está `en tránsito`**; un renglón que
pasara a "probablemente recibido" dejaría de estarlo y su producto **se
volvería a proponer** —el doble pedido que el 24 vino a impedir— antes de que
nadie confirmara nada. Habría que acordarse de agregarlo a tres `WHERE`, a dos
tuplas y a un CHECK, y un olvido no daría ningún error.

Lo que cuesta, dicho: la propuesta se recalcula en cada carga, con tres lecturas
más (lo que está en tránsito y lo recibido, de `pedidos`; las compras desde el
envío más viejo, de `marts`) y una cuarta pequeña (qué productos han aparecido
alguna vez en compras). Son unas cuantas filas: lo en camino es poco, y las
compras de unos días son decenas.

### Por qué el rechazo guarda qué compras, y no una fecha tope

La opción a (no recordar) es la trampa que el ticket nombra: la misma propuesta
rechazada volvería mañana, y pasado, y el encargado aprendería a no mirar el
bloque.

La opción b se ve más simple y **esconde compras en silencio**: una compra
capturada el viernes a las 19:30 —después del respaldo de las 18:51— llega al
almacén hasta el lunes con fecha de viernes. Si el sábado alguien rechazó la del
viernes en la mañana, la fecha tope se tragaría la de la tarde sin que nadie la
viera nunca. Guardar el `compra_id` —la llave de SICAR, no el folio— es exacto:
rechazar dice *esta compra no es este pedido*, y nada más.

La firma del rechazo es la del **último** que rechazó, y es un costo aceptado:
guardar una firma por compra rechazada exigiría la tabla de cruce. Si alguna vez
importa quién rechazó cada una, la bitácora lo tiene (la ruta escribe quién, qué
renglón y qué compras).

### Por qué columnas y `bigint[]`, y no una tabla

Una tabla nueva obliga a volver a correr `crear_rol.sql` —el paso que más se
olvida y el que peor avisa (ADR 0007, 0008, 0012)—. Lo que se guarda son una o
dos compras por renglón, que se leen con el renglón y se comparan con `&&`
("tienen algún elemento en común") dentro del `WHERE` de confirmar. Nadie las
consulta sueltas. Si algún día hace falta preguntar "¿qué renglón confirmó esta
compra?" a menudo, un índice GIN sobre la columna lo resuelve antes que una
tabla.

### Por qué solo se confirma lo que trae al menos lo pedido

El glosario dice que `recibido` es **"llegó completo"** y que `recibido parcial`
es "llegó menos de lo pedido; lo que faltó vuelve a proponerse". Confirmar como
completo una compra de 3 contra un pedido de 5 (opción A) cerraría el renglón en
falso y las 2 que faltaron **no se volverían a pedir nunca** — exactamente el
daño que el ADR 0002 nombra. Y la opción C es el ticket 27 entero: lo que faltó
tiene que volver, y eso es otra regla.

Así que la cantidad **se enseña siempre** —trae 3 de las 5, o trae 8 y se
pidieron 5— y el botón de confirmar solo aparece cuando la evidencia alcanza. La
condición está **dos veces a propósito**: en la función pura, que decide qué
ofrecer, y en el `WHERE` de `_CONFIRMAR_LA_RECEPCION`
(`coalesce(r.cantidad_final, r.cantidad_propuesta) <= :piezas`), con `:piezas`
calculado por la misma función. Es el patrón del límite del atraso del 25: la
pantalla y la base no pueden separarse.

**La puerta del 27 queda abierta**: el CHECK de la recepción ya pide firma para
`recibido parcial`, y `recibido_con_compras` admite `NULL` en lo recibido —el
marcado a mano no tiene compras—. Lo que el 27 tiene que hacer es escribir,
no rediseñar.

Si la compra trae **más**, se confirma y se dice qué puede significar: otro
pedido del mismo producto, o una bonificación. No se reparte el sobrante entre
renglones: eso sería afirmar a qué pedido pertenecen piezas que SICAR no sabe.

### Por qué una compra que encaja con dos se dice en los dos

Asignarla en silencio al más viejo es la opción que se propone sola y es la que
peor falla: si en realidad era del pedido nuevo, el viejo se cierra con
evidencia ajena y el nuevo se queda esperando una compra que ya "se usó". Nadie
vería nada.

Repartir sus piezas es inventar un reparto que SICAR no tiene.

Lo que se hizo: la compra aparece en las dos propuestas, **cada una dice que la
comparte** ("una compra confirma un solo renglón: el primero que se confirme se
la queda"), y el `WHERE` de confirmar lleva un `NOT EXISTS` con `&&` contra
`recibido_con_compras` de cualquier otro renglón. La persona decide cuál es;
la tabla impide que decida las dos.

Lo que se renuncia: una sola compra de 10 que de verdad surtió dos pedidos de 5
solo puede confirmar uno. El otro se queda esperando, y su salida es el marcado a
mano del ticket 27.

### Por qué el día del envío, en la hora de la farmacia, y por qué el mismo día cuenta

La compra solo tiene **día**. Comparar un día contra un instante obliga a elegir
en qué zona se corta el instante, y la respuesta es la de la farmacia: SICAR
corre en la máquina del mostrador, en hora local. Un envío del lunes a las 20:30
son las 02:30 del martes en UTC; contado en UTC, la compra del lunes quedaría
fuera. El cálculo vive en Python (`dia_del_envio`) porque en Postgres
`at time zone '-06'` se lee UTC+6.

**El mismo día cuenta** porque es el caso de todos los días: se captura en el
portal a las 9 y el proveedor surte a las 15. Exigir "estrictamente después"
dejaría sin propuesta la mitad de las entregas. Lo que eso deja pasar de más —una
compra de esa misma mañana que era de otro pedido— es justo lo que la persona
juzga con la evidencia enfrente, y por eso esto se sugiere y no se afirma.

### Por qué la lista de hoy entra

`_LO_YA_PEDIDO` mira solo listas anteriores (`< :antes_de`) porque es la memoria
con la que se **arma** una lista. La recepción no arma nada: lo enviado esta
mañana puede llegar esta tarde. Por eso hay una lectura hermana,
`_EN_TRANSITO`, sin fecha de lista, que además trae el `pro_id` del pedido.

### Por qué los que nunca van a tener propuesta se dicen primero

Un renglón a QuePharma, o de un producto que nunca ha aparecido en compras, se
quedaría esperando una propuesta que no va a llegar, y a los N días se vería
atrasado. La pantalla los enseña **arriba de los que solo esperan**, con la
frase de por qué, y dice que su única salida —el recibido a mano— **todavía no
existe** en esta pantalla. No se pinta un botón que no hay.

"Nunca aparece en compras" es una lectura del almacén (`productos_con_compras`,
sobre `fct_compras`, que el rol ya lee): si esa lectura falla, **no se afirma
"nunca"** —se dice "todavía no aparece", que es lo que sí se sabe (regla 4)—.

## Consecuencias

- **Migración 0010** y lo mismo en `crear_tablas.sql`. **No crea tabla**:
  `crear_rol.sql` **no** hace falta volver a correrlo. **Y tampoco hace falta
  ningún permiso nuevo sobre `marts`**: las dos lecturas nuevas son sobre
  `fct_compras` y `dim_fecha`, que ya estaban otorgadas. `verificar_rol.sql`
  gana las comprobaciones 34 y 35. **La 0010 va antes de desplegar**: las
  lecturas de renglones nombran las columnas nuevas.
- **Dos rutas**: `POST /api/renglon/{id}/recepcion/confirmar` y
  `.../rechazar`, con `{"compras": [...]}` —lo que la persona vio—. La ruta
  **vuelve a calcular** la propuesta con las mismas lecturas y contesta 409 si
  ya no es la misma. Firma con el correo de Access: firma, nunca permiso.
- **El bloque de la recepción** va en la respuesta de la lista, arriba de lo
  que viene en camino, con el aviso de que una noche de retraso es normal
  **siempre** a la vista.
- **La advertencia del 25 cambia de alcance, no desaparece.** Un renglón
  atrasado **con propuesta** ya no ofrece devolverlo —se confirma o se rechaza
  primero—; uno **sin** propuesta sigue pudiendo ser algo que llegó sin dejar
  compra, y la advertencia junto al botón lo dice así.
- **Un pedido con algo recibido ya no ofrece cancelar**, en la partición de hoy
  y en el bloque de listas anteriores: el `NOT EXISTS` que el 25 dejó puesto se
  ejercita ahora de verdad.
- **Condición de revisión.** El ADR 0002 ya la dejó escrita: *si la recepción
  sugerida acierta en más del 90% de los casos durante un mes, ahí sí vale la
  pena cerrarla sola*. Con `recibido_con_compras` y `compras_rechazadas`
  guardados, esa tasa ya se puede medir: confirmadas contra rechazadas, por
  mes. Y la del 25: con un mes de recepciones, medir de `enviado_en` a
  `recibido_en` y ajustar N.
