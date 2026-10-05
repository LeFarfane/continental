# Sesiones al abrir: la ventana flotante y el botón de probar

Status: ready-for-agent

Decisiones del dueño del 2026-10-05, en el ADR 0024. El vocabulario (Sesión,
Probar, `sirvió`, `caducada`, `guardada, sin probar`) está en `CONTEXT.md`, y
manda sobre cualquier nombre de este documento.

## El problema

Sin sesión, un portal no da precios, y casi todo Continental se apoya en esos
precios: el lote nocturno, la comparación del pedido y buscar. Aun así, quien
abre Continental llega directo a la lista del día. Las sesiones están en una
pestaña aparte que nadie mira antes de empezar.

Además, lo que dice cada tarjeta de Sesiones no se preguntó en ese momento.
Se deduce de lo que otras consultas encontraron de paso, y puede tener horas.
Doyle sigue diciendo `guardada` después de que el portal caducó la sesión:
pasó el 2026-09-19 y el 2026-09-26, cuando LEVIC dejó de servir nueve horas y
media después de abrirse (ADR 0019). Hoy no hay manera de preguntarle al
portal, en el momento, si la sesión sigue pasando del login.

## La solución

- **Al abrir Continental aparece una ventana flotante con las cuatro
  sesiones.** Es la imagen espejo de la pestaña Sesiones: las mismas
  tarjetas, los mismos botones y «Probar todas» arriba. Desde ahí se puede
  abrir una sesión, darle «Ya entré» y probar, sin cambiar de pestaña. Se
  cierra con «Continuar» o con Esc, y no impide trabajar.
- **La ventana vuelve a salir** cada vez que se abre o se recarga la página, y
  cuando la pestaña pasa una hora sin un clic ni una tecla.
- **Probar** busca «paracetamol 500» en el portal y dice si la sesión pasó del
  login (`sirvió`) o la mandó al login (`caducada`). El resultado se guarda,
  y la tarjeta muestra el más reciente que haya, venga de una prueba o de una
  consulta.
- **Una prueba a la vez en todo Continental.** Mientras corre, los botones de
  probar quedan apagados en todas las computadoras.

## Historias de usuario

1. Como encargado, quiero ver las sesiones apenas abro Continental, para saber
   antes de empezar si los portales van a dar precios.
2. Como encargado, quiero que la ventana flote sobre la pantalla sin
   bloquearla, para poder cerrarla y ver la lista de ayer o En camino aunque
   una sesión esté caída.
3. Como encargado, quiero cerrar la ventana con «Continuar», para seguir con
   mi trabajo.
4. Como encargado que usa el teclado, quiero cerrar la ventana con Esc, para
   no tener que buscar el botón con el ratón.
5. Como encargado, quiero que la ventana vuelva a salir cuando recargo la
   página, para que cada vez que empiezo vea las sesiones.
6. Como encargado que dejó la PC sola una hora, quiero que al volver aparezca
   la ventana, porque en una hora una sesión pudo haber caducado.
7. Como encargado que está trabajando, quiero que la ventana no me interrumpa
   mientras uso la pantalla, para no perder lo que estoy haciendo.
8. Como encargado, quiero que la hora sin uso se cuente en cada computadora
   por separado, para que alguien usando Continental en la torre no le quite
   la ventana a quien vuelve a la PC de la farmacia, ni al revés.
9. Como encargado, quiero que la ventana muestre lo mismo que la pestaña
   Sesiones, para no aprender dos pantallas.
10. Como encargado, quiero que la pestaña Sesiones tenga los mismos botones de
    probar que la ventana, para probar también desde ahí.
11. Como encargado, quiero un botón «Probar» en cada tarjeta, para revisar un
    solo portal en unos segundos, sin esperar a los cuatro.
12. Como encargado, quiero un botón «Probar todas» arriba de las cuatro
    tarjetas, para revisarlas de una vez en la mañana.
13. Como encargado, quiero que probar no corra solo, para que abrir o recargar
    la página no gaste búsquedas en los cuatro portales.
14. Como encargado que acaba de darle «Ya entré», quiero que no se lance una
    prueba sola, porque acabo de ver con mis propios ojos que entré.
15. Como encargado, quiero que después de «Ya entré» la tarjeta diga
    `guardada, sin probar`, para saber que el sistema todavía no lo comprobó.
16. Como encargado, quiero que la prueba diga `sirvió` cuando el portal
    contestó sin mandarme al login, aunque no traiga precio de ese producto,
    porque lo que pregunto es si la sesión vive.
17. Como encargado, quiero que la prueba diga `caducada` cuando el portal me
    mandó al login, para saber que tengo que volver a abrirla.
18. Como encargado, quiero que una tarjeta `caducada` me ofrezca volver a
    abrir la sesión ahí mismo, para arreglarlo sin cambiar de pantalla.
19. Como encargado, quiero que una prueba que no terminó (Doyle no responde,
    el portal no contesta) muestre un error con su motivo, para saber que no
    se comprobó nada.
20. Como encargado, quiero que esa prueba fallida no le cambie la etiqueta a
    la tarjeta, porque no saber no es lo mismo que `caducada`.
21. Como encargado, quiero que la tarjeta muestre la etiqueta más reciente,
    venga de una prueba o de una consulta del pedido, para no ver un `sirvió`
    viejo encima de un `caducada` nuevo.
22. Como encargado, quiero que la frase de la tarjeta diga de dónde viene la
    etiqueta y a qué hora, por ejemplo «probada a las 9:00» o «una consulta la
    encontró caducada a las 11:00», para saber cuánto confiar en ella.
23. Como encargado, quiero que mientras corre una prueba los botones de probar
    se apaguen, para no lanzar una segunda encima de la primera.
24. Como encargado en la PC de la farmacia, quiero que esos botones también se
    apaguen si la prueba la pidió alguien desde otra computadora, porque se
    hace contra los mismos portales.
25. Como encargado, quiero que un botón apagado diga por qué, para no pensar
    que la pantalla se trabó.
26. Como encargado, quiero ver que una prueba está corriendo, porque probar
    los cuatro tarda medio minuto.
27. Como encargado, quiero que al terminar la prueba las tarjetas se vuelvan a
    pintar con el resultado, sin recargar la página.
28. Como encargado, quiero que el portal que está esperando en el visor no se
    pruebe y que su botón de probar quede apagado con el motivo, porque esa
    ventana es de quien está tecleando.
29. Como encargado, quiero que «Probar todas» pruebe los otros tres aunque uno
    esté esperando en el visor, y que diga cuál se saltó, para no quedarme sin
    probar nada.
30. Como encargado, quiero que la prueba busque algo que manejan los cuatro
    proveedores, para que también muestre precios y no solo que pasó del
    login.
31. Como dueño, quiero que el término de prueba esté en la configuración, para
    cambiarlo sin tocar código si un día deja de servir.
32. Como dueño, quiero que la sonda del lote nocturno busque el mismo término,
    para que exista una sola manera de comprobar una sesión.
33. Como dueño, quiero que la sonda del lote no guarde su resultado, porque
    solo decide si el lote corre y su rastro ya queda en la corrida y en el
    journal.
34. Como dueño, quiero que cada prueba quede guardada con su hora y su
    resultado, para poder medir cuánto dura de verdad una sesión de cada
    portal.
35. Como dueño, quiero que las pruebas no lleven firma, porque probar no
    cambia nada del pedido y no hay nada que auditar.
36. Como encargado, quiero que si Doyle no responde la ventana aparezca igual,
    mostrando el hueco con su motivo, para no confundir "sin sesiones" con
    "no pude preguntar".
37. Como encargado que entra desde el celular, quiero que la ventana quepa en
    una pantalla angosta sin desplazamiento lateral, para poder usarla igual.
38. Como encargado que la usa en oscuro, quiero que la ventana respete la
    Apariencia elegida, para que no me deslumbre.
39. Como quien usa un lector de pantalla, quiero que la ventana se anuncie
    como diálogo, que el foco entre en ella al abrirse y regrese a donde
    estaba al cerrarla, para no perderme.

## Decisiones de implementación

- **Una sola función pinta las tarjetas** de la ventana y de la pestaña.
  Recibe dónde pintar y a quién avisarle cuando un paso termina. Dos copias se
  separan solas, y el dueño pidió explícitamente una imagen espejo.
- **La ventana es un `<dialog>` modal** en el HTML estático, como el de
  confirmar el cierre. Se abre después de la primera carga, y otra vez cuando
  la pestaña pasa una hora sin clics ni teclas. La hora se cuenta en memoria,
  dentro de la pestaña, sin `localStorage`, porque se mide por computadora y
  por pestaña. Se cierra con «Continuar» o con Esc, y el foco vuelve a donde
  estaba.
- **Una ruta nueva para probar**, un POST, con una lista de proveedores
  opcional; vacía quiere decir los cuatro.
  - **Se niega con 409** si ya hay una prueba corriendo, y dice cuál.
  - **Se salta el portal que está esperando en el visor** y lo reporta con su
    motivo.
  - Si se pidió solo ese portal, se niega diciendo por qué.
  - Contesta con el resultado de cada portal probado.
  - Usa la búsqueda que Doyle ya tiene, con su lista de proveedores, y espera
    a que termine con el mismo patrón de la sonda del lote.
- **El candado de "una prueba a la vez" vive en el servidor, en memoria del
  proceso**, porque tiene que valer entre computadoras. Continental es un
  solo proceso; si un reinicio suelta el candado, a lo más se pierde una
  prueba a medias, y eso no hace daño.
- **`GET /api/sesiones` suma tres datos:**
  - si hay una prueba en curso, para que cada tarjeta y «Probar todas» se
    apaguen;
  - por tarjeta, si se puede probar, y si no, el motivo;
  - la etiqueta, decidida con la prueba guardada más reciente además de las
    consultas guardadas.

  Como hoy, todo llega dicho del servidor; el JavaScript solo pinta.
- **La decisión de la etiqueta sigue en la función pura de `sesiones`**:
  gana la evidencia más reciente, sea prueba o consulta, y la frase nombra su
  origen y su hora. `sirvió` cambia de "dio precio" a "pasó del login":
  precio, `sin resultados` o `no empareja` cuentan; solo `la sesión caducó`
  es `caducada`. Las pruebas de hoy que dependen del significado anterior se
  ajustan a propósito.
- **Una tabla nueva que solo crece**, en el esquema propio de Continental,
  con una fila por portal probado: negocio, proveedor, hora (`timestamptz`) y
  un resultado que el `CHECK` limita a `sirvió` o `caducada`. Sin firma y sin
  precio. El rol `continental` puede insertar y leer, pero no actualizar ni
  borrar (regla 6). Al desplegar se revisa la forma de la base antes de
  reiniciar (ADR 0017), así que la migración va con su verificación.
- **Una prueba que no termina no escribe nada.** Contesta la falla con
  `que_hacer`, como las demás llamadas a Doyle, y nunca con el `str` de la
  excepción (regla 5). El JS la pinta como nota fija, no como aviso pasajero
  (enmienda del 2026-10-05 al ADR 0023).
- **El término de prueba** es una línea de configuración del pedido, con el
  valor «paracetamol 500». Sustituye a `clave_de_sonda`, que hoy apunta a
  SIGDAN.
  - La sonda del lote lo usa, y ya no necesita el respaldo de "el primer
    renglón con EAN de la lista".
  - Sin el término, la prueba y el lote fallan ruidosamente; no se elige otro
    en silencio.
- **«Ya entré» no cambia**: sigue sin probar nada.
- **Los dobles crecen con lo mínimo**:
  - el doble de almacenamiento guarda y lee pruebas igual que el SQL;
  - el doble de Doyle ya sabe pedir búsquedas con una lista de proveedores.

## Decisiones de prueba

- **Una buena prueba aquí mira lo que sale del sistema**, no cómo está hecho
  por dentro: la respuesta HTTP, las filas que quedan guardadas, el JSON que
  pinta la pantalla. Como es costumbre del repo, ninguna prueba toca Postgres
  de verdad, ni Doyle, ni la red, ni duerme.
- **Donde se prueba casi todo: la API HTTP**, con los fixtures `cliente`,
  `doyle` y `almacenamiento`. Es lo que ya hace `test_sesiones.py`, que es el
  ejemplo a seguir. Casos:
  - probar uno y probar todos;
  - `sin resultados` cuenta como `sirvió` y `la sesión caducó` como `caducada`;
  - Doyle caído no guarda nada y la etiqueta anterior se queda;
  - una segunda prueba recibe 409 mientras corre la primera;
  - el portal que espera en el visor se salta, y si se pidió solo ese, se
    niega;
  - después de probar, `GET /api/sesiones` trae la etiqueta nueva;
  - una consulta posterior a la prueba le gana a la prueba, y al revés;
  - las fallas no llevan el texto de la excepción.
- **La función pura de la etiqueta**, por tabla de casos: prueba contra
  consulta, cuál es más reciente, y la nueva definición de `sirvió`. Mismo
  estilo que las pruebas de `estado_de_la_sesion` que ya existen.
- **El doble de almacenamiento contra el SQL**: la misma regla que la prueba
  que hoy compara el doble con el SQL de la evidencia.
- **El lote**, en `test_lote.py`, como ahora:
  - la sonda busca el término configurado;
  - sin término, falla ruidosamente;
  - la sonda no escribe ninguna prueba.
- **Lo estático del HTML, el CSS y el JS** se revisa sobre el texto, como en
  `test_conciliacion_js.py` y `test_pasada_visual.py`, porque aquí no se
  ejecuta JavaScript:
  - el `<dialog>` existe;
  - la ventana y la pestaña llaman a la misma función de pintar;
  - existe el contador de una hora;
  - Esc y «Continuar» cierran la ventana;
  - no hay colores fuera de `:root`;
  - las frases no se componen en el JS.
- **Las guardias de forma de la base** (`test_forma.py`, `test_despliegue.py`)
  cubren la tabla nueva y su `CHECK`.

## Fuera del alcance

- Que el lote o la ventana prueben solos, por un horario o al abrir.
- Que «Ya entré» lance una prueba.
- Guardar el resultado de la sonda del lote.
- Firmar quién probó.
- Avisar fuera de la pantalla (correo, Uptime Kuma) cuando una prueba da
  `caducada`.
- Averiguar por qué caduca la sesión de LEVIC, o volver a armar el timer del
  lote (ADR 0019).
- La sesión de Cloudflare Access, que es otra cosa y no es una Sesión del
  glosario.
- Cambios en Doyle: su búsqueda ya acepta una lista de proveedores.

## Notas

- El nombre de la ruta, de la tabla y de la línea de configuración los decide
  quien implemente, respetando el glosario. «Probar» es el verbo canónico.
- La tabla de pruebas permite medir algo que hoy solo se conoce por dos
  incidentes: cuánto dura una sesión de cada portal. Si ese dato muestra que
  las sesiones aguantan de forma confiable, se cumple la condición de revisión
  del ADR 0019.
- ADR 0024, condición de revisión: si la ventana termina cerrándose sin
  leerla, se revisa el intervalo de una hora o la regla de cuándo aparece.
