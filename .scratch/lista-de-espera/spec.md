# Lista de espera, mínimo del proveedor, total por pedido y el EAN que abre el portal

Status: ready-for-agent

Decisiones del dueño del 2026-10-05, en la enmienda de ese día al ADR 0025.
El vocabulario (Mandar a espera, Lista de espera, Mínimo del proveedor,
Capturado, Pedido, Renglón) está en `CONTEXT.md`, y manda sobre cualquier
nombre de este documento.

## El problema

La encargada arma la lista, la reparte y llega a la pantalla de captura. Ahí
le faltan cuatro cosas:

1. **No ve cuánto dinero lleva cada pedido** sin entrar a cada proveedor. La
   columna izquierda solo dice «0 de 9» (renglones tachados), y el tope del
   dueño es en dinero.
2. **No tiene cómo guardar un pedido que no se va a mandar hoy.** Hay dos
   motivos: se pasa del tope del dueño, o no llega al mínimo que el proveedor
   pide para surtir. «Pasar al día siguiente» existe, pero solo desde Revisar,
   renglón por renglón, y al día siguiente se vuelve a repartir: se pierde a
   quién se le iba a pedir y no se puede juntar hasta el mínimo.
3. **Nadie sabe cuál es el mínimo de cada proveedor** dentro de Continental,
   así que nada avisa que un pedido no llega.
4. **Copiar el EAN no basta.** Después de copiarlo tiene que cambiar de
   ventana, ir al buscador del portal y pegarlo, renglón por renglón.

## La solución

- La columna izquierda de la captura dice **el total en dinero de cada
  pedido**, la misma cifra del botón «Enviar»: *«NADRO · $1,661.94 · 0 de 9»*.
- **«Mandar a espera»** reemplaza a «Pasar al día siguiente». Se manda un
  renglón (en Revisar, como hoy, y además en Captura) o el pedido entero de un
  proveedor (en Captura). Lo que espera **conserva su proveedor**, y cuando se
  arma la lista siguiente **entra solo al pedido de ese proveedor**, sumado a
  lo que se vendió desde entonces.
- Una pestaña nueva, **Ajustes**, guarda el **mínimo de cada proveedor** tal
  como él lo dice: con o sin IVA. Un pedido debajo del mínimo **se avisa, no
  se bloquea**, con «Mandar a espera» a la mano.
- **Un clic en el EAN copia y abre el portal** en una pestaña nueva. En NADRO y
  VICMA cae ya en la búsqueda del producto; en LEVIC y QuePharma, que buscan
  con un formulario, abre su página de búsqueda para pegar. Las direcciones
  las da **Doyle**, que ya las tiene configuradas.
- Al cerrar una lista se **avisa** lo que venía de la espera y nadie tocó:
  se va a dar por atendido, y reabrir deja de servir en cuanto se arma la
  siguiente.

## Historias de usuario

### El total en la columna izquierda

1. Como encargada, quiero ver el total en dinero de cada pedido en la columna
   izquierda de la captura, para saber de un vistazo si nos pasamos del tope
   del dueño.
2. Como encargada, quiero que ese total sea exactamente la misma cifra del
   botón «Enviar» de ese pedido, para no tener dos números que no cuadran.
3. Como encargada, quiero que el total baje en cuanto mando un renglón a
   espera, para ver al momento cuánto recorté.
4. Como encargada, quiero seguir viendo cuántos renglones llevo tachados junto
   al total, para no perder lo que ya me decía la columna.
5. Como encargada, cuando un renglón del pedido no tiene precio, quiero que el
   total lo diga («$1,200 + 2 sin precio»), para no creer que el total está
   completo cuando no lo está.
6. Como dueño, quiero ver el total de cada pedido junto a su mínimo, para
   decidir si se manda hoy o se espera.

### Mandar a espera un renglón

7. Como encargada, quiero un botón «Mandar a espera» en cada renglón de la
   captura, para recortar un pedido sin regresar a Revisar.
8. Como encargada, quiero que el botón que hoy dice «Pasar al día siguiente»
   en Revisar diga «Mandar a espera», para que haya un solo nombre para lo
   mismo.
9. Como encargada, quiero que un renglón mandado a espera salga del pedido de
   hoy y de su total, para que el total refleje lo que de verdad se va a pedir.
10. Como encargada, quiero que el renglón en espera recuerde a qué proveedor
    se le iba a pedir, para no tener que volver a repartirlo mañana.
11. Como encargada, quiero devolver un renglón de la espera con un clic,
    mientras la lista siga abierta, para corregir un error sin diálogo.
12. Como encargada, quiero que un renglón devuelto regrese al pedido de su
    proveedor, para no tener que repartirlo otra vez.
13. Como encargada, quiero que un renglón tachado no se pueda mandar a espera
    sin destacharlo primero, porque ya está en el carrito del portal.
14. Como encargada, quiero que el renglón en espera diga quién lo mandó y
    cuándo, para saber a quién preguntarle.
15. Como encargada, quiero que mandar a espera desde Revisar, antes de
    repartir, funcione como hoy: sin proveedor, y que se reparta de nuevo
    mañana.

### Mandar a espera el pedido entero

16. Como encargada, quiero un botón «Mandar a espera» por pedido en la
    captura, para guardar todo NADRO de un clic cuando no llega al mínimo.
17. Como encargada, quiero que el botón del pedido mande solo los renglones no
    tachados, porque lo tachado ya está en el carrito del portal.
18. Como encargada, quiero que me diga cuántos mandó y cuántos se quedaron por
    estar tachados, para saber que tengo que borrarlos del carrito o
    destacharlos.
19. Como encargada, quiero que un pedido sin renglones abiertos después de
    mandarlo a espera se vea vacío y no como enviado, para no confundirlo con
    algo que ya se pidió.

### La lista siguiente

20. Como encargada, quiero que lo que esperaba entre solo al pedido de su
    proveedor en la lista siguiente, para no tener que acordarme de ir a
    buscarlo.
21. Como encargada, quiero que si el producto se volvió a vender, las piezas
    se junten en un solo renglón, para no capturarlo dos veces.
22. Como encargada, quiero que el renglón diga la aritmética («se vendieron 2
    y esperaban 3, se piden 5»), para poder verificarla de un vistazo.
23. Como encargada, quiero que el renglón que vuelve de la espera diga desde
    cuándo espera y cuántas listas lleva, para ver si algo se está quedando
    para siempre.
24. Como encargada, quiero que si otro proveedor da más barato el producto que
    volvió de la espera, la tarjeta lo diga como hoy, para decidir si lo
    cambio.
25. Como encargada, quiero que lo que viene en camino le gane a lo que
    esperaba, como hoy, para no pedir dos veces lo mismo.
26. Como encargada, quiero volver a mandar a espera algo que ya venía de la
    espera, sin contar dos veces sus piezas, para seguir juntando hasta el
    mínimo.
27. Como dueño, quiero que la espera no tenga tope de veces pero que el
    contador de listas esté a la vista, para que alguien decida cuando algo
    lleva demasiado.

### Al cerrar

28. Como encargada, quiero que al cerrar se me avise qué renglones venían de
    la espera y nadie tocó, para no perderlos sin darme cuenta.
29. Como dueño, quiero que, si nadie lo atiende, lo que volvió de la espera se
    dé por atendido al cerrar, igual que todo lo demás, para que la lista no
    arrastre cosas sin fin.
30. Como encargada, quiero que el aviso diga que reabrir deja de servir en
    cuanto se arma la lista siguiente, para saber que es ahora o nunca.
31. Como encargada, quiero que un renglón que está en espera al cerrar **no**
    aparezca en el aviso, porque ya tiene adónde ir.

### El mínimo del proveedor y Ajustes

32. Como dueño, quiero una pestaña Ajustes en la página principal, para
    capturar el mínimo de cada proveedor.
33. Como dueño, quiero capturar el mínimo como lo dice el proveedor y marcar
    si incluye IVA, para no hacer cuentas al capturarlo.
34. Como dueño, quiero que cualquiera con acceso pueda cambiar un mínimo y que
    quede firmado quién y cuándo, para saber quién lo movió.
35. Como encargada, quiero ver en la captura el mínimo de cada pedido junto a
    su total, comparados en la misma base de IVA, para saber si llega.
36. Como encargada, quiero un aviso, no un bloqueo, cuando el pedido no llega
    al mínimo, porque a veces conviene pagar el flete o el proveedor hace
    excepción.
37. Como encargada, quiero que el aviso diga cuánto falta («faltan $260 para
    el mínimo de NADRO»), para decidir si junto más o espero.
38. Como encargada, quiero que un proveedor sin mínimo capturado diga «sin
    mínimo capturado» en gris y no avise nada, para no confundirlo con «no
    tiene mínimo».
39. Como dueño, quiero poder decir que un proveedor no tiene mínimo (cero) y
    que eso sea distinto de no haberlo capturado.
40. Como dueño, quiero que Ajustes rechace un mínimo negativo o con texto, y
    que diga por qué.
41. Como dueño, quiero que solo aparezcan en Ajustes los proveedores que
    Continental conoce, para no capturar el mínimo de uno que no existe.

### El EAN que abre el portal

42. Como encargada, quiero que un clic en el EAN lo copie y abra el portal de
    ese proveedor en una pestaña nueva, para no tener que buscar la ventana.
43. Como encargada, quiero que en NADRO y VICMA la pestaña caiga ya en la
    búsqueda del producto, para no pegar nada.
44. Como encargada, quiero que en LEVIC y QuePharma se abra su página de
    búsqueda con el EAN ya copiado, para solo pegar.
45. Como encargada, quiero que el botón diga en su título qué va a pasar
    («Copiar y abrir la búsqueda en NADRO» o «Copiar y abrir LEVIC para
    pegar»), para saber si tengo que pegar.
46. Como encargada, quiero que si Doyle no contesta el EAN se siga copiando
    como hoy y se diga que no se pudo abrir el portal, para no quedarme sin
    nada.
47. Como encargada, quiero que si el navegador bloquea la pestaña nueva se
    muestre un enlace para abrirla a mano.
48. Como encargada, quiero que la pestaña nueva se abra siempre en la misma
    ventana por proveedor, para no acabar con veinte pestañas de NADRO.
49. Como dueño, quiero que la dirección la arme el servidor y no el navegador,
    para que Continental nunca mande a un portal algo que alguien escribió.

### Doyle, como dependencia

50. Como Continental, quiero que Doyle me diga, por HTTP y solo lectura, la
    dirección de búsqueda de cada portal y si busca por dirección o por
    formulario, para no copiar esa configuración en dos repos.
51. Como dueño, quiero que esa ruta de Doyle no exponga usuarios, contraseñas
    ni nada de la sesión, solo direcciones públicas de los portales.

## Decisiones de implementación

### El total por pedido

- El total lo calcula el **servidor** y viaja en la respuesta de la captura,
  por pedido; el navegador solo lo pinta. Es la **misma función** que hoy da la
  cifra de «Enviar», no una segunda suma: dos sumas acaban por no cuadrar.
- La base del total sigue siendo la de hoy (costo sin IVA). Los renglones sin
  precio se cuentan aparte y se dicen («+ 2 sin precio»), nunca como cero
  (regla 4).
- Los renglones en espera y los descartados no cuentan.

### Mandar a espera

- **El estado sigue siendo `pospuesto`** en la base. Cambian el nombre en
  pantalla y las frases: «Mandar a espera», «En espera», «Lista de espera».
- **El renglón guarda el proveedor de la espera** en una columna nueva,
  escrita al mandarlo a espera. Se toma del pedido al que estaba repartido; si
  no estaba repartido, del proveedor elegido a mano; si no hay ninguno, queda
  vacío y la lista siguiente lo reparte como hoy. El renglón **sale de su
  pedido** (deja de pertenecerle) en la misma transacción.
- **Devolverlo** (`pospuesto` → `abierto`) lo regresa al pedido de ese
  proveedor en la misma lista, si ese pedido sigue en `borrador`. Si el pedido
  ya no está en `borrador`, el renglón vuelve sin repartir y se dice por qué.
- Mandar a espera rechaza un renglón **capturado** (tachado), con su motivo, en
  el mismo lugar donde hoy viven los motivos para no editar
  (`transiciones`).
- **El pedido entero** es una operación del servidor, no un ciclo de clics en
  el navegador: una sola transacción que manda a espera los renglones
  abiertos y no tachados de ese pedido, y devuelve cuántos mandó y cuántos se
  quedaron por estar tachados.
- Una migración nueva (la siguiente después de la 0019) agrega al renglón: el
  proveedor de la espera; **desde cuándo espera** (la fecha de la primera vez
  que se mandó, la que se arrastra), y **cuántas listas lleva**. Sus CHECK se
  repiten en Python, como el resto de las columnas del renglón.

### La lista siguiente

- Se lee lo que espera igual que hoy se lee lo pospuesto: de la lista
  **inmediatamente anterior**. "No caduca" sale de que se puede volver a
  mandar a espera tantas veces como haga falta, no de leer listas más viejas.
- Al armar la lista, un renglón que viene de la espera **nace ya repartido** al
  proveedor de la espera: su pedido en `borrador` de ese proveedor se crea o se
  reutiliza. La elección lleva la firma de quien lo mandó a espera y su hora,
  porque fue una persona la que decidió el proveedor.
- Si el producto también se vendió, es **un solo renglón** con las piezas
  sumadas, con el proveedor de la espera. Se conserva lo que hoy hace
  `piezas_pospuestas` (no se cuenta doble si se vuelve a mandar).
- Desde cuándo espera y cuántas listas lleva se **copian y suman** al renglón
  nuevo. Lo que viene en camino le sigue ganando (regla 6 del ADR 0025).

### Al cerrar

- El cierre agrega un grupo al aviso de lo que se perdería: los renglones
  **abiertos** que trajeron piezas de la espera. Los que están en espera al
  cerrar siguen fuera del aviso.
- La frase dice las piezas, desde cuándo esperaban y que reabrir deja de
  servir en cuanto se arma la lista siguiente.

### El mínimo del proveedor y Ajustes

- Una **tabla propia** (migración nueva): negocio, proveedor, monto, si
  incluye IVA, quién y cuándo. Una fila por negocio y proveedor; se sobreescribe
  con su firma y no guarda historial. Que no haya fila quiere decir «sin mínimo
  capturado»; un cero quiere decir «no tiene mínimo». El rol `continental`
  escribe en ella (regla 6) y el permiso se da en la migración.
- **Ajustes** es una pestaña nueva de la pantalla principal, con una fila por
  proveedor conocido (los mismos de la correspondencia), un campo de monto y
  la casilla «incluye IVA». Guardar es una ruta del servidor que valida
  (número, ≥ 0, proveedor conocido) y firma con el correo de Access (regla 3:
  firma, no permiso).
- **La comparación contra el total la hace el servidor**, en la base que diga
  el mínimo: si el mínimo incluye IVA, el total se lleva a con-IVA con la
  misma función que ya usa el puente; nunca se restan dos cifras en bases
  distintas (la trampa de Marlowe). El resultado viaja ya como frase y
  estado (`llega`, `no llega` con lo que falta, `sin mínimo capturado`).

### El EAN que abre el portal

- **Doyle** agrega una ruta GET de solo lectura que devuelve, por proveedor,
  la dirección de búsqueda y si busca por dirección. Nada más: ni la dirección
  del login ni la sesión ni el perfil. Prueba en el repo de Doyle.
- **Continental** pide esa ruta por su cliente de Doyle y **arma el enlace en
  el servidor** con el EAN del renglón. Si el portal busca por dirección, el
  enlace lleva el EAN; si no, es la página de búsqueda sola. El navegador no
  manda ningún término (la misma regla del ADR 0026, punto 4).
- La respuesta de la captura trae, por renglón, el enlace y si es «ya
  buscado» o «para pegar». Si Doyle no contestó, el enlace no viene y la
  frase lo dice; el botón sigue copiando.
- En el navegador, el clic en el EAN **copia y abre** con `window.open` en una
  ventana nombrada por proveedor (`portal-nadro`, …), con el mismo enlace de
  respaldo que «Abrir sesión» si el navegador la bloquea. Esto no rompe la
  regla 1: Continental no controla un navegador, le da un enlace a una
  persona.
- La pestaña cae en el navegador de la farmacia, donde ya capturan con la
  sesión del dueño abierta. Si no hay sesión ahí, el portal muestra su login;
  eso no se detecta ni se arregla aquí.

## Decisiones de prueba

Una buena prueba aquí mira lo que el sistema **dice y guarda**, no cómo lo
hace: la frase, el estado del renglón, el total que viaja, la fila que se
escribe. Ninguna prueba toca Postgres, la red ni duerme, y ningún dato es
real. Los cuatro niveles de siempre, sin abrir uno nuevo:

1. **Lo puro.** El total por pedido (con renglones sin precio y en espera), la
   comparación contra el mínimo en las dos bases de IVA y sin mínimo, de qué
   proveedor hereda la espera, la suma de piezas y del contador al armar, las
   frases («esperaban 3», «faltan $260», «sin mínimo capturado») y el grupo
   nuevo del aviso de cierre. Antecedente: `test_posponer.py`,
   `test_cierre.py`, `test_comparacion.py`.
2. **Lo guardado.** El doble del almacenamiento cumple la interfaz nueva
   (mandar a espera con proveedor, el pedido entero, devolver al pedido, el
   mínimo firmado), los CHECK en Python de las columnas nuevas y el SQL como
   texto (que mandar a espera saca del pedido, que el pedido entero respeta lo
   tachado). Antecedente: `test_posponer.py`, `test_guardado.py`,
   `test_sql_del_pedido.py`.
3. **Las rutas de punta a punta, varios días.** Mandar a espera un renglón y
   el pedido entero desde la captura; armar la lista siguiente y ver el
   renglón ya repartido con su aritmética y su contador; cerrar con algo que
   volvió de la espera y ver el aviso; guardar un mínimo en Ajustes (y
   rechazar uno inválido); que la captura traiga el enlace del EAN con el
   doble de Doyle, y que sin Doyle siga copiando y lo diga. Antecedente:
   `test_posponer.py` (sección de rutas), `test_captura.py`,
   `test_ver_en_portal.py`, con el doble de Doyle de `dobles.py`.
4. **Estáticas sobre el texto del JS.** La columna izquierda pinta el total
   del servidor y no lo suma; los dos botones de «Mandar a espera» en la
   captura; el clic del EAN copia y abre en una ventana nombrada por
   proveedor, con su respaldo; la pestaña Ajustes existe y manda a la ruta.
   Antecedente: `test_completar_js.py`, `test_ver_en_portal_js.py`. Si se
   agregan `fetch`, se actualiza el conteo de sitios de `fetch` en las tres
   pruebas que lo fijan.

En Doyle, una prueba de la ruta nueva: devuelve los cuatro proveedores con su
dirección de búsqueda y su modo, y **no** devuelve la dirección del login ni
nada de la sesión.

## Fuera del alcance

- Abrir la búsqueda en el **visor de Doyle** en vez de una pestaña nueva. Queda
  para cuando la pestaña dé fricción (decisión del dueño, 2026-10-05).
- Detectar si el portal de la pestaña nueva pide login.
- Un **tope de dinero** en la pantalla que recorte solo: el recorte lo sigue
  haciendo una persona (ADR 0025, opciones descartadas).
- Historial de cambios del mínimo: solo el valor actual con su firma.
- Bloquear «Enviar» debajo del mínimo.
- Una vista aparte de la lista de espera entre listas: lo que espera se ve en
  el bloque de la lista donde se mandó y, al día siguiente, dentro de su
  pedido.
- Renombrar el estado `pospuesto` en la base.
- Otros ajustes en la pestaña Ajustes: nace solo con el mínimo.

## Notas

- La condición de revisión del ADR 0025 (lo pospuesto que se vuelve a pasar
  día tras día) se cumple ahora **a propósito**: el contador de listas es la
  forma de verla.
- El orden natural de los tickets: Doyle primero (no bloquea lo demás), luego
  el total, después mandar a espera con proveedor y la lista siguiente, el
  cierre, el mínimo con Ajustes y al final el EAN que abre el portal.
- Desplegar Continental antes que Doyle no rompe nada: sin la ruta, el EAN se
  sigue copiando y la frase dice que no se pudo armar el enlace.
