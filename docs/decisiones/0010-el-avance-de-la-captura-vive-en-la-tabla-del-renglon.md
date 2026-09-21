# 0010 — El avance de la captura vive en la tabla del renglón, no en el navegador

**Fecha:** 2026-09-21  ·  **Estado:** aceptada

## Contexto

El ticket 22 construye el **modo real de trabajo**: el encargado tiene el portal
del proveedor abierto en una ventana y esta pantalla en otra, y va tachando
renglones conforme los captura. Con un pedido de 40 renglones eso son 40 idas y
vueltas entre dos ventanas, y la tercera casilla dice lo único que hace falta
saber para decidir:

> *el avance sobrevive a recargar la página: nadie quiere empezar de nuevo a la
> mitad de 40 renglones.*

"Sobrevivir a recargar" tiene dos respuestas posibles, y son de naturalezas
distintas: **guardar el avance en el navegador** —`localStorage`, que sobrevive
a la recarga por su cuenta— o **guardarlo en las tablas de Continental**, que
cuesta una migración y a cambio lo hace un dato del negocio como cualquier otro.

Lo que empuja la decisión hacia un lado no es la recarga —las dos la aguantan—
sino la quinta casilla:

> *Marcar todo como capturado es lo que **habilita** enviar el pedido, sin
> obligar a ello.*

Enviar es **la declaración firmada de que el pedido ya se capturó en el portal**
(ADR 0009), y es la que mueve los renglones a `en tránsito` para que el sugerido
de mañana no los vuelva a proponer. Así que el avance de la captura deja de ser
una comodidad de la interfaz: es lo que lleva a la única acción de este módulo
que compromete dinero real.

Tres cosas ya escritas delimitan el problema, y ninguna se decide aquí:

1. **Regla 3 de `CLAUDE.md`:** el correo de Access es una **firma**, nunca un
   permiso. Todo lo que una persona decide en este módulo va firmado —
   `descartado_por`, `ajustada_por`, `elegido_por`, `enviado_por`.
2. **Regla 7:** toda tabla dice a qué negocio pertenece.
3. **ADR 0003:** el rol `continental` no puede crear tablas, así que cualquier
   columna nueva es una migración a mano con credenciales de dueño.

## Opciones consideradas

1. **`localStorage` del navegador**, con una llave por pedido.
2. **`sessionStorage` o una cookie.**
3. **Una tabla nueva**, `pedidos.captura_de_renglon`, una fila por renglón
   tachado.
4. **Un estado nuevo del renglón**, `capturado`, entre `abierto` y
   `en tránsito`.
5. **Dos columnas firmadas en `pedidos.renglon`** —`capturado_por`,
   `capturado_en`— pareadas por un CHECK. *(elegida)*

## Decisión

**La quinta.** El avance vive en `pedidos.renglon`, en dos columnas nuevas que
son una **firma** con la misma forma que las otras cuatro del esquema:

```sql
capturado_por text,        -- el correo que verificó Access
capturado_en  timestamptz, -- cuándo lo dijo
CONSTRAINT ck_renglon_captura
    CHECK ((capturado_por IS NOT NULL) = (capturado_en IS NOT NULL))
```

`NULL` en las dos quiere decir **"nadie lo ha tachado"**. Migración
`sql/migraciones/0007-el-avance-de-la-captura.sql`, y lo mismo dentro de
`sql/crear_tablas.sql` para una base desde cero. **No crea tabla**, así que
`sql/crear_rol.sql` no hace falta volver a correrlo.

De ahí salen cuatro reglas concretas:

- **Se puede destachar**, y eso lo aparta del envío. Un clic de más en una lista
  de 40 es ordinario, y mientras el pedido siga en `borrador` nada depende
  todavía de la marca. Destachar borra las dos columnas: no se guarda quién
  destachó, porque lo que la columna afirma es *"esto está capturado"* y lo
  contrario es la ausencia de la afirmación, no una segunda afirmación.
- **Solo sobre un pedido en `borrador`**, y solo sobre renglones `abierto` que
  cuelguen de él. Un pedido `enviado` ya no se edita (ADR 0009) y sus marcas
  quedan como quedaron: son la historia de cómo se capturó.
- **NO exige que la lista siga `abierta`**, por la misma razón que enviar no lo
  exige (ADR 0009): tachar es decir *"esto ya lo tecleé en el portal"*, que es
  lo contrario de modificar lo que se va a pedir. Si lo exigiera, quien cierre
  la lista antes de terminar de capturar se quedaría sin poder tachar y, por el
  camino de la quinta casilla, sin el empujón hacia enviar.
- **Tacharlo todo NO es condición para enviar.** `se_puede_enviar` no mira la
  captura ni una sola vez: lo que la marca completa cambia es que la pantalla
  **invita** a enviar, con la frase hecha desde Python. Enviar con cero
  renglones tachados sigue funcionando igual que antes de este ticket, y hay una
  prueba que lo fija.

## Razones

### Por qué no la 1 (`localStorage`)

Es la opción gratis y por eso hay que decir con precisión qué se pierde. Cuatro
cosas, y la última sola ya decide:

- **Dos pestañas divergen en silencio.** `localStorage` es por origen, así que
  las dos pestañas comparten la llave pero **no se enteran una de la otra**
  salvo que alguien escuche el evento `storage` y resuelva el conflicto. Con dos
  pestañas del mismo pedido abiertas —que es exactamente lo que este ticket
  describe como modo de trabajo— la última que escriba gana y la otra sigue
  enseñando lo suyo. Es la misma razón por la que los conteos de esta pantalla
  salen del servidor y no de una cuenta del JavaScript, escrita ya en
  `web/app.py` desde el ticket 10.
- **Cambiar de máquina pierde el avance entero.** El mostrador tiene una
  computadora y el dueño mira desde otra; el encargado que empieza a capturar en
  una y sigue en otra —o el que termina lo que otro dejó a medias— empieza de
  cero, que es literalmente lo que la tercera casilla prohíbe. La casilla dice
  "recargar la página" porque es el caso obvio, no porque sea el único.
- **No hay firma, y en este módulo todo lo que una persona decide la lleva**
  (regla 3). Sin ella, cuando la factura de NADRO no cuadre no hay a quién
  preguntarle qué se tecleó — que es exactamente la pregunta que el ADR 0009
  contesta para el pedido entero y que aquí se contesta renglón por renglón.
- **Y lo que decide: el avance es lo que lleva a enviar.** La quinta casilla
  convierte "tachar todo" en el gesto que empuja hacia la acción que compromete
  dinero. Un dato que lleva a esa acción y que vive solo en el perfil de un
  navegador no se puede auditar, no se puede ver desde otro dispositivo y
  desaparece con un "limpiar datos del sitio" sin dejar rastro.

Hay además una falla concreta y silenciosa: **volver a partir cambia qué
renglones están dentro de cada pedido**. Una llave `captura:<pedido_id>` con
ids dentro seguiría diciendo que el renglón 41 está capturado después de que el
renglón 41 se fue al pedido de LEVIC. En la tabla no puede pasar: la marca vive
en el renglón, viaja con él, y el `WHERE` que la escribe exige que el renglón
cuelgue de un pedido en `borrador`.

Lo que sí se queda en el navegador es lo que **de verdad** es del navegador: qué
vista está encendida (`vistaRecordada`, ticket 06) y qué bloque está abierto.
Son preferencias de quien mira, no hechos del pedido.

### Por qué no la 2 (`sessionStorage` o cookie)

`sessionStorage` muere al cerrar la pestaña, así que aguanta la recarga y no
aguanta un cierre accidental — la mitad peor de la casilla. Una cookie viaja en
cada petición y tiene 4 KB: cuarenta ids no caben cómodos y, sobre todo,
mandarle al servidor un dato que el servidor no puede verificar es fingir que se
guardó.

### Por qué no la 3 (una tabla nueva)

Es un hecho **por renglón** con un solo valor posible —o está tachado o no—, y
eso son dos columnas en la fila que ya existe, no una tabla. Una tabla aparte
solo se gana su sitio cuando hay muchos hechos por renglón con su propio
instante, que es exactamente el caso de `pedidos.precio_de_proveedor` (cuatro
proveedores por renglón, tabla que solo crece, ADR 0004) y **no** el de esto.

Y cuesta algo medible: **cada tabla nueva obliga a volver a correr
`sql/crear_rol.sql`**, porque un permiso no se puede dar sobre una tabla que
todavía no existe. `HANDOVER.md` documenta con detalle lo que pasa cuando ese
paso se olvida —con la migración 0004 el lote de la noche rebota con *permission
denied*, no aborta la corrida, y la pantalla miente a la mañana siguiente—. Dos
columnas no lo piden: el `GRANT SELECT, INSERT, UPDATE` es sobre la tabla
entera y aquí no se usan permisos por columna, a propósito.

### Por qué no la 4 (un estado nuevo del renglón)

Es la opción que parece la más limpia y es la que rompe cosas.

`CONTEXT.md` define los estados del renglón como su camino hacia la mercancía:
`abierto`, `en tránsito`, `recibido`, `recibido parcial`, `descartado`.
`capturado` no es un punto de ese camino: mientras el pedido siga en `borrador`
**no se le ha pedido nada a nadie**, y el ticket 20 dejó escrito con todas sus
letras que un renglón dentro de un borrador **sigue `abierto`**.

Y romperlo no es teórico. `_ASIGNAR_RENGLONES` y `_SOLTAR_RENGLONES` llevan
`estado = 'abierto'` en su `WHERE`: un renglón en un estado `capturado` dejaría
de poder moverse, así que **volver a partir se lo saltaría en silencio** y el
pedido se quedaría con un renglón que el total ya no cuenta. Lo mismo con
`_DESCARTAR` y con `_AJUSTAR_LA_CANTIDAD`. Un estado nuevo entre `abierto` y
`en tránsito` es una bifurcación en un camino que hoy tiene cuatro sentencias
apoyadas en que no la hay.

La marca de captura es **ortogonal** al estado: dice qué hizo una persona con su
teclado en otra ventana, no dónde está la mercancía. Por eso va en columnas
propias, como la corrección de la cantidad y como la elección de proveedor, que
también son cosas que una persona hizo sin que el renglón cambie de estado.

### Por qué se puede destachar, si enviar no se puede deshacer

Son dos declaraciones de distinto tamaño y conviene decirlo, porque parecen la
misma. `enviado` no se deshace porque **la mercancía ya está pedida en el portal
del proveedor** y un botón de aquí no la despide (ADR 0009). Una marca de
captura no cambia nada fuera de esta pantalla mientras el pedido siga en
`borrador`: no mueve un renglón a `en tránsito`, no toca un total y no impide ni
habilita nada. Lo único que hace es llevar la cuenta.

Lo que sí se cierra es después: una vez `enviado`, el `WHERE` deja de dejar
tachar y destachar, igual que deja de dejar todo lo demás.

### Por qué no se guarda quién destachó

Porque no hay un hecho que guardar. La columna afirma *"este renglón se capturó
en el portal"*; lo contrario de esa afirmación es su ausencia, no otra
afirmación. Guardar `destachado_por` obligaría a una tercera columna y a un
CHECK con tres estados para contestar una pregunta que nadie hace. El día que
alguien la haga —"¿quién deshizo esto?"— la respuesta es una tabla de bitácora
de verdad, no un remiendo aquí; hoy queda en el `log.info` de la ruta, que sí
escribe las dos direcciones con su firma.

## Consecuencias

- **`pedidos.renglon` gana dos columnas y un CHECK** (`ck_renglon_captura`), con
  su migración `0007` y lo mismo en `sql/crear_tablas.sql`. **No crea tabla**,
  así que `crear_rol.sql` no hace falta volver a correrlo; `verificar_rol.sql`
  sí, por su comprobación **29**, que es nueva.
- **Una ruta nueva**, `POST /api/renglon/{id}/capturado`, que devuelve **la
  lista entera** como hacen `partir` y `enviar`: tachar cambia el avance de su
  pedido y la invitación a enviar, y deducir eso en el navegador es justo lo que
  esta pantalla no hace.
- **`particion.Linea` gana la clave del producto y la firma de la captura**, y
  con eso la pantalla de captura y la vista previa de la partición se calculan
  con el mismo código — la regla de qué precio le toca a cada línea sigue
  escrita una sola vez (`particion._linea`).
- **El orden de los renglones tachados no cambia.** Mandar lo tachado al final
  movería bajo el dedo la lista que alguien está recorriendo. Se distinguen por
  cómo se ven, no por dónde están.
- **Lo que este ADR no decide:** qué pasa cuando la mercancía llega. Eso es el
  ticket 26. La marca de captura **no** es un dato de recepción y no debe
  usarse como tal: dice que alguien tecleó un renglón en un portal, no que el
  proveedor lo haya aceptado ni que vaya a llegar.
- **Condición de revisión.** Si con el uso resulta que los pedidos se envían
  casi siempre con cero renglones tachados, esta pantalla no está sirviendo para
  lo que se construyó y el avance guardado es peso muerto. Se mide con
  `select count(*) filter (where capturado_por is not null), count(*) from
  pedidos.renglon where pedido_id is not null` sobre los pedidos ya enviados.
