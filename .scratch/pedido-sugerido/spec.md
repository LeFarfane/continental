# Módulo de Pedido: reponer lo vendido y comprarle al más barato

Status: ready-for-agent

## El problema

Quien arma el pedido a NADRO lo hace de memoria y de anaquel. Dos hechos
medidos dicen lo que eso cuesta:

- Los dos productos que más utilidad dejan en la farmacia estuvieron en
  existencia cero.
- El mismo EAN salió a **$86.05 en NADRO** y **$146.38 en LEVIC** el mismo día:
  **70% de diferencia**. Nadie lo supo al reponer, porque el dato de precio
  vivía en compras pasadas y no en el precio de hoy.

Hoy, para saber a cómo está un producto en los cuatro proveedores, hay que
abrir Doyle, buscarlo uno por uno y comparar a ojo. Nadie lo hace para 40
productos a las 8 de la mañana, así que en la práctica todo se le pide a NADRO
y el sobreprecio no se ve.

Y no hay memoria de lo ya pedido: si el martes se pidieron 3 piezas y llegan el
jueves, el miércoles el producto sigue vendido y con existencia baja, así que se
vuelve a pedir.

## La solución

Un módulo dentro de Continental que:

1. **Arma solo el pedido sugerido de cada día** con lo que se vendió, en
   reposición 1 a 1, acumulando desde el cierre del pedido sugerido anterior.
2. **Consulta de noche el precio y la existencia en los cuatro proveedores**
   por EAN, a través de Doyle, con un tope de 60 minutos y en orden de
   importancia.
3. **Presenta una pantalla** donde el encargado ve cada renglón con su
   existencia, sus días de cobertura y el precio de los cuatro, con el más
   barato marcado y el ahorro a la vista; descarta lo que no va, elige
   proveedor por renglón, y captura en el portal tachando renglones conforme
   avanza.
4. **Recuerda lo pedido.** Un renglón enviado queda `en tránsito` y no se
   vuelve a proponer. Cuando aparece una compra que encaja, el renglón se marca
   **probablemente recibido** y espera un clic; lo que el proveedor no surtió
   vuelve a proponerse.

El vocabulario exacto está en `CONTEXT.md` y manda sobre cualquier sinónimo. El
porqué de cada regla está en `docs/decisiones/0002`.

## Historias de usuario

**Armar la lista del día**

1. Como encargado, quiero abrir Continental en la mañana y encontrar el pedido
   sugerido del día ya armado, para no tener que pedirle a nadie que lo genere.
2. Como encargado, quiero que la lista traiga lo que se vendió desde el último
   pedido sugerido que cerré, para que un día en que no alcancé a pedir no se
   pierda.
3. Como encargado, quiero que el lunes la lista junte el viernes por la tarde y
   el sábado completo, porque esos datos llegan juntos y no quiero descubrir el
   martes que faltó reponer algo del sábado.
4. Como encargado, quiero que la primera vez que uso el módulo la lista arranque
   con los últimos 7 días, para tener una lista con volumen suficiente desde el
   primer día.
5. Como encargado, quiero ver en la lista **cuántas piezas se vendieron** de
   cada producto y que la cantidad propuesta sea esa misma, para poder
   verificar la propuesta de un vistazo.
6. Como encargado, quiero poder cambiar la cantidad de un renglón antes de
   pedirlo, porque a veces sé algo que el sistema no.
7. Como encargado, quiero ver la fecha exacta de ventas que alimentó la lista,
   para saber si estoy viendo datos de ayer o del viernes pasado.
8. Como dueño, quiero que la lista diga cuándo se armó y con qué corte, para
   poder auditar por qué un producto entró o no entró.

**Decidir qué entra**

9. Como encargado, quiero un interruptor entre "medicamentos y botica" y "todo
   lo vendido", para no ver refrescos y botanas cuando estoy armando el pedido
   de la farmacia.
10. Como encargado, quiero que los productos de los anaqueles de patente,
    genérico, naturista, botica y vitrina cuenten como medicamento, porque a
    todos ésos se les compra a los mismos proveedores.
11. Como encargado, quiero que un producto vendido **sin anaquel conocido**
    aparezca siempre, marcado como *sin clasificar*, para que no desaparezca de
    la lista sin que nadie se entere.
12. Como dueño, quiero saber cuántos renglones quedaron *sin clasificar*, para
    decidir si vale la pena ponerles anaquel en SICAR.

**Leer la lista**

13. Como encargado, quiero ver la existencia actual de cada producto junto a la
    cantidad propuesta, para decidir si de verdad hace falta.
14. Como encargado, quiero ver los días de cobertura de cada renglón, para
    distinguir lo que se va a acabar mañana de lo que tiene anaquel lleno.
15. Como encargado, quiero que la lista venga ordenada por urgencia, para que
    lo que importa esté arriba y lo que no, abajo.
16. Como encargado, quiero descartar un renglón de un clic, para limpiar la
    lista sin tener que pensar dos veces en lo mismo.
17. Como encargado, quiero ver los renglones descartados en algún lado, para
    poder recuperar uno si me equivoqué.
18. Como dueño, quiero ver qué se descartó cada día, porque si se descarta la
    mitad de la lista todos los días, la regla de reposición está mal.

**Comparar precios**

19. Como encargado, quiero ver el precio de compra de cada producto en los
    cuatro proveedores, para saber a quién pedirle.
20. Como encargado, quiero ver marcado cuál es el más barato y cuánto me ahorro
    contra NADRO, para justificar partir el pedido.
21. Como encargado, quiero ver la existencia que reporta cada proveedor, porque
    el más barato no sirve si no lo tiene.
22. Como encargado, quiero que un proveedor que no encontró el producto diga
    **"sin dato"** y no un precio en blanco ni un cero, para no confundir "no
    sé" con "más caro".
23. Como encargado, quiero saber **por qué** falta un precio —sesión caducada,
    el portal no contestó, no se alcanzó el tope de tiempo—, para saber si
    puedo resolverlo yo.
24. Como encargado, quiero un botón que vuelva a consultar los precios que
    faltan, para completarlos en la mañana sin esperar a la noche.
25. Como encargado, quiero poder consultar el precio de un renglón concreto
    cuando quiera, sin lanzar el lote completo.
26. Como dueño, quiero que la comparación solo empareje productos por código de
    barras, para no comparar una caja de 30 contra una de 60 y creer que es más
    barato.
27. Como dueño, quiero saber cuántos renglones quedaron sin comparar, para
    entender qué tan buena es la respuesta a "¿NADRO nos da el mejor precio?".

**El lote de la noche**

28. Como dueño, quiero que los precios se consulten solos después de la cadena
    nocturna, para que en la mañana la lista ya esté completa.
29. Como dueño, quiero que el lote se detenga a los 60 minutos, para no tener a
    un robot tocando los portales de mis proveedores media noche.
30. Como dueño, quiero que el lote consulte primero lo que más pesa en la
    utilidad, para que lo que se quede sin precio sea siempre lo que menos
    importa.
31. Como encargado, quiero que la lista me diga "faltan precios porque el lote
    se cortó por tiempo", distinto de "el portal falló", para saber qué hacer.
32. Como dueño, quiero que si el lote no termina, Uptime Kuma me avise, igual
    que ya me avisa la cadena de ventas.
33. Como encargado, quiero que una sesión de proveedor caducada me lo diga en la
    pantalla con el botón para abrirla, en vez de tener que entrar a otra
    aplicación.

**Pedir**

34. Como encargado, quiero elegir el proveedor de cada renglón, porque hay
    razones —mínimo de pedido, días de entrega, crédito— que el sistema no ve.
35. Como encargado, quiero que un pedido sugerido se pueda partir en varios
    pedidos, uno por proveedor, para pedirle a cada quien lo que conviene.
36. Como encargado, quiero ver el pedido de un proveedor en una pantalla con
    casillas, para ir tachando mientras capturo en su portal.
37. Como encargado, quiero exportar el pedido a CSV, para abrirlo en Excel o
    guardarlo.
38. Como encargado, quiero marcar el pedido como enviado cuando termino de
    capturarlo en el portal, para que el sistema sepa que ya está en camino.
39. Como encargado, quiero ver el total del pedido en pesos antes de enviarlo,
    para saber cuánto voy a comprometer.
40. Como dueño, quiero que quede registrado quién armó y quién envió cada
    pedido, para saber a quién preguntarle.

**No pedir dos veces**

41. Como encargado, quiero que un renglón ya pedido no vuelva a aparecer en la
    lista de mañana, para no pedir doble.
42. Como encargado, quiero ver los renglones en tránsito en algún lado, con su
    fecha y su proveedor, para saber qué estoy esperando.
43. Como encargado, quiero que un renglón lleve más de N días en tránsito me lo
    señale, porque eso significa que el proveedor no lo mandó.
44. Como encargado, quiero poder cancelar un pedido que nunca capturé, para que
    sus renglones vuelvan a la lista.

**Recibir**

45. Como encargado, quiero que cuando llegue la mercancía y se capture en SICAR,
    el sistema me proponga solo que ese renglón ya llegó, para no marcarlo a
    mano.
46. Como encargado, quiero que eso se llame **probablemente recibido** y espere
    mi clic, porque los datos de SICAR no alcanzan para afirmarlo.
47. Como encargado, quiero marcar que llegó menos de lo pedido, para que la
    diferencia vuelva a proponerse.
48. Como encargado, quiero marcar a mano que algo llegó aunque el sistema no lo
    haya emparejado, porque un pedido puede llegar en dos facturas.
49. Como dueño, quiero ver en qué se basó el emparejamiento —proveedor,
    producto, cantidad, fecha de la compra—, para juzgar si tiene sentido.

**Quién es quién**

50. Como dueño, quiero que cada acción quede firmada con el correo de quien la
    hizo, para reconstruir después qué pasó.
51. Como encargado, quiero entrar sin escribir otra contraseña, porque
    Cloudflare Access ya me identificó.
52. Como dueño, quiero que si alguien entra sin identificarse, las acciones
    queden firmadas como *sin identificar* y no atribuidas a una persona.

**Cuando algo falla**

53. Como encargado, quiero que si Doyle no contesta, la lista igual se vea y me
    diga que los precios no están disponibles, en vez de una pantalla en
    blanco.
54. Como encargado, quiero que si el almacén no responde, me lo diga con
    claridad y no me muestre una lista vacía que parezca "hoy no se vendió
    nada".
55. Como dueño, quiero que ningún error del servidor me mande al navegador
    detalles de la conexión a la base.

## Decisiones de implementación

### Dónde vive

Todo dentro de Continental (`src/continental/`). Doyle no cambia para esto más
allá de lo que ya define su ADR 0008. Marlowe no participa: su precio es de
mostrador de un competidor, no de compra.

### Módulos nuevos

- **Lectura del almacén** — una interfaz de solo lectura sobre `marts` que
  devuelve **datos, no conexiones**: ventas de un rango, catálogo con anaquel y
  existencia, compras posteriores a una fecha. Es el borde del proceso y se
  sustituye en las pruebas.
- **Cliente de Doyle** — el otro borde: pedir una búsqueda, consultar su estado,
  listar sesiones. También se sustituye en las pruebas.
- **Clasificación** — función pura: anaquel y categoría de un producto →
  `medicamento` / `abarrote` / `sin clasificar`. Lee sus listas de
  `config/continental.yml`.
- **Sugerido** — función pura: ventas + catálogo + corte → el pedido sugerido
  con sus renglones, ya ordenados por urgencia.
- **Lote de precios** — orquesta las consultas a Doyle con su tope de tiempo y
  su orden; separa la decisión (qué consultar, en qué orden, cuándo parar) de
  la llamada.
- **Emparejamiento por EAN** — función pura: resultado de un proveedor + clave
  buscada → precio aceptado o motivo de rechazo.
- **Recepción** — función pura: renglones en tránsito + compras posteriores →
  propuestas de "probablemente recibido" con su evidencia.
- **API y pantallas** — FastAPI sobre lo anterior.

### Cómo se inyectan las dependencias

**Ninguna de estas piezas crea su conexión ni su cliente al importarse.** Se
entregan por `Depends` de FastAPI y se sustituyen en las pruebas con
`app.dependency_overrides`.

Esto es a propósito y contradice el precedente: Marlowe parchea módulos con
`monkeypatch` porque su `web/app.py` abre SQLite, crea el motor de Postgres y
verifica la pantalla **al importarse**, y el costo es un fixture de ~100 líneas
con un `DISPLAY` falso y una URL de Postgres muerta. Continental no hereda eso.

### Tablas nuevas en Postgres

Tres, con rol propio `continental`, que solo escribe lo suyo y de `marts` solo
lee. **Toda fila lleva el código de negocio**, aunque hoy siempre valga
`farmacia_01`.

- **`pedido_sugerido`** — uno por día y negocio. Estado: `abierto` → `cerrado` →
  `vencido`. Guarda **hasta qué momento de ventas consideró**, que es lo que
  permite que el siguiente acumule desde ahí.
- **`renglon`** — producto, cantidad propuesta, cantidad final, existencia y
  cobertura al momento de proponerlo, clasificación, y los precios leídos por
  proveedor con su momento de lectura. Estado: `abierto` → `en tránsito` →
  `recibido` / `recibido parcial`, o `descartado`.
- **`pedido`** — uno por proveedor, nacido de renglones. Estado: `borrador` →
  `enviado` → `recibido` / `recibido parcial`, o `cancelado`. Guarda quién lo
  envió y cuándo.

El precio de un renglón se **congela** al leerlo, con su fecha: un pedido dice a
qué precio se decidió, no a cómo está hoy.

### Reglas que el código tiene que respetar

- **Anclar en `max(fecha)`, nunca en el reloj.** El Postgres del contenedor
  corre en UTC y su `current_date` puede ir dos días adelante del último dato.
  A farmacia-data le costó 11.7 puntos de crecimiento inventados.
- **Reposición 1 a 1**, sin filtrar por cobertura. La cobertura solo ordena.
- **Emparejamiento solo por EAN.** NADRO y LEVIC lo muestran directo. **VICMA se
  acepta únicamente si la búsqueda del EAN devuelve exactamente un resultado.**
  QuePharma usa código interno y probablemente quede fuera: eso es `sin dato`.
- **El orden de importancia sale de `clase_abc` de `dim_producto`** (ADR 0018 de
  farmacia-data). Mientras esa columna no exista, el módulo no puede ordenar
  como se especificó: **es un prerrequisito, no un detalle**.
- **Un renglón en tránsito no se propone de nuevo.** Lo no surtido de un
  `recibido parcial` vuelve a `abierto` para el siguiente sugerido.
- **La recepción propone, no afirma.** El emparejamiento es por proveedor,
  producto y fecha posterior al envío; nunca por `folio`, cuya semántica no está
  verificada.
- **Los errores no viajan al navegador**: detalle a la consola, mensaje genérico
  al cliente.
- **La identidad es una firma, no un permiso.** Se lee de
  `Cf-Access-Authenticated-User-Email` y vale `sin-identificar` si no viene. No
  hay acciones restringidas por rol.
- **Un módulo caído es un hueco con motivo**, con su timeout por llamada.

### Configuración

Los números viven en `config/continental.yml`, no en el código:
`dias_primera_vez` (7), `tope_lote_minutos` (60), los anaqueles de medicamento y
de abarrote, las categorías de abarrote, y la dirección y timeout de cada
módulo.

## Decisiones de prueba

### Qué es una buena prueba aquí

Una que solo mira **comportamiento externo**: entra por la API, sale por la
respuesta. Si una prueba conoce el nombre de una función interna, la estructura
de una tabla o el orden en que se llamó a algo, está probando implementación y
va a romperse en el primer refactor honesto.

Además, siguiendo lo que ya hace Marlowe: **cada archivo de pruebas abre con un
docstring que explica por qué existe**, con la fecha del error real que lo
originó cuando lo haya. Eso convierte el suite en documentación de fallas.

### La costura: una sola

**La API HTTP, por `TestClient`**, con los dos bordes del proceso sustituidos
mediante `app.dependency_overrides`: la lectura del almacén y el cliente de
Doyle. Por ahí se prueban la clasificación, la acumulación desde el corte, el
orden por urgencia, el tope del lote, las transiciones de estado y el
emparejamiento de recepción.

**Ninguna prueba toca Postgres.** Marlowe llegó a 223 pruebas en menos de un
segundo justamente así, y es la razón por la que las funciones que importan
reciben datos y no conexiones.

Lo que sí hay que cubrir por esa costura, y no se debe olvidar:

- Un proveedor que no contesta deja `sin dato`, no un cero ni un precio vacío.
- VICMA con dos resultados para un EAN **no** produce precio.
- Un renglón en tránsito no aparece en el siguiente sugerido.
- Un `recibido parcial` devuelve la diferencia a la lista.
- Un producto sin anaquel sale marcado *sin clasificar* y nunca se cae de la
  lista.
- El lote que se corta por tiempo marca lo que faltó con ese motivo, distinto de
  un fallo de portal.
- El sugerido del lunes incluye las ventas del viernes por la tarde y del
  sábado.
- Un error del servidor devuelve un mensaje genérico, sin detalle de conexión.

### Prueba estática, aparte de la costura

**Copiar `test_compila.py` de Marlowe**: `ast.parse` sobre todo `src/`, más el
chequeo de CRLF y shebang en scripts y unidades de systemd. Son ~20 líneas y
nació de un servicio en bucle de reinicio con 148 pruebas en verde.

### Fixtures

Recortes literales, versionados, con fecha y procedencia en el docstring; se
cargan con un `read_text` directo, sin factories. Para este módulo son filas de
ventas, catálogo y compras, **agregadas y sin datos personales**: nada de
`cliente`, `usuario` ni CFDI, ni siquiera como ejemplo.

### El chequeo de despliegue, que no es una prueba

`continental.verificar`, con la misma partición que el de Marlowe: funciones
puras que **reciben datos** y devuelven un informe (esas sí se prueban con
pytest) y funciones de recolección que leen de Postgres (esas no). Acumula todas
las fallas en vez de detenerse en la primera, y **cada mensaje de falla incluye
el comando de reparación**. Corre desde `desplegar.sh` antes de reiniciar el
servicio.

Invariantes mínimos: no hay dos pedidos sugeridos abiertos para el mismo día y
negocio; ningún renglón en tránsito sin su pedido; ningún pedido enviado sin
quién lo envió; el rol `continental` puede leer de verdad las tablas de `marts`
que necesita (probándolo con un `SELECT 1`, porque cada `dbt build` recrea
tablas y borra permisos).

## Fuera de alcance

- **Llenar el carrito de NADRO o hacer el pedido en el portal.** El módulo
  genera la lista; una persona captura. Automatizar la compra es una decisión
  nueva, con su propio ADR.
- **Mudar Doyle a atlas.** Es prerrequisito y va primero, pero es otro trabajo:
  ADR 0008 de Doyle.
- **La columna `clase_abc`.** También prerrequisito, en farmacia-data: ADR 0018.
- **Mínimos, máximos, empaques y cajas.** El pedido se expresa en piezas.
- **La tarjeta O2 de Metabase.** Se queda como tablero de análisis; no alimenta
  el pedido ni se modifica.
- **Max/punto-interno.** Sus productos no están en SICAR y no se le compran a
  estos proveedores.
- **Absorber la interfaz de Marlowe.** Va después de este módulo.
- **Aislamiento entre farmacias.** Se guarda el código de negocio en todas las
  tablas y nada más.
- **Comparar contra precios de cadenas.** Es precio al público, no de compra.
- **CI.** No existe en ninguno de los repos hermanos; sigue siendo un hueco
  conocido, no parte de este trabajo.

## Notas

**Prerrequisitos, en orden:** Doyle en atlas (ADR 0008 de Doyle) → `clase_abc`
en `dim_producto` (ADR 0018 de farmacia-data) → este módulo.

**El horario del respaldo está en `propuesta`** (ADR 0017 de farmacia-data): lo
decide el dueño. Si se acepta mover el respaldo a las ~20:15, hay que mover el
timer de la cadena a las 21:00 en el mismo movimiento, o el colchón baja de hora
y media a 15 minutos. El módulo no depende de eso: acumula desde el corte
precisamente para no depender.

**Hechos que hay que tener presentes al implementar:**

- Las ventas llegan tarde: el respaldo sube hacia las 18:51 de lunes a viernes,
  la cadena corre a las 20:30, y lo del sábado llega hasta el lunes en la noche.
  Peor caso, 2.5 días.
- SICAR no tiene pedidos ni órdenes de compra: una compra se captura ya
  recibida, `status` solo vale 1 o -1, y no está documentado si `compra.fecha`
  es el día que llegó o el día que se capturó.
- 606 de 3,429 artículos (17.7%) nunca aparecen en `fct_compras`, 128 de ellos
  con existencia. Para ésos, el emparejamiento de recepción no va a proponer
  nada nunca.
- 688 de 3,429 artículos no tienen anaquel.
- Una búsqueda en Doyle tiene un piso de ~9 segundos por proveedor y un techo de
  60-90 si se estiran los timeouts. El tope de 60 minutos es lo que hace que eso
  no se salga de control.

**Cuándo está terminado** (esto y no "ya corre"): un día de operación real en
que la lista se armó sola de noche con las ventas del día anterior, trajo
precios de los cuatro proveedores, una persona la revisó, descartó lo que no
iba, capturó el pedido en NADRO leyendo de la pantalla, y al día siguiente los
renglones se marcaron como probablemente recibidos cuando la compra apareció en
el almacén. **Con al menos un renglón donde NADRO no era el más barato y se le
pidió a otro.**
