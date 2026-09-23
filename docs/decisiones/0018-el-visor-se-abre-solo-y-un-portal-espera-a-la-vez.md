# 0018 — El botón abre el visor, y solo un portal puede estar esperando a la vez

**Fecha:** 2026-09  ·  **Estado:** aceptada

## Contexto

Doyle se mudó a atlas el 2026-09-21 (su ADR 0008) y abre el navegador del
portal en una pantalla Xvfb, `:98`, que solo se ve por un visor remoto
—`x11vnc` en `127.0.0.1:5900` más `websockify`/noVNC en `172.19.0.1:6080`,
publicado en `doyle.farfanlab.uk` con Cloudflare Access delante—.

El texto que Continental devolvía al apretar «Abrir sesión» se escribió el
2026-09-19, cuando Doyle corría en la torre, y mandaba a la persona a teclear
*"en la máquina donde corre Doyle"*. Desde la mudanza esa máquina es un
servidor sin monitor. **La frase dejó de ser cierta y nadie la movió.**

Lo que costó, medido en los dos journals del 2026-09-21:

| Hora | Hecho |
|---|---|
| 19:30:26 | `continental-web`: se pidió abrir la sesión de LEVIC. La ventana se abrió. |
| 19:39:50 | `doyle-visor-web`: `404`. Se entró a la raíz de noVNC, que sirve `/usr/share/novnc` **sin `index.html`**: un listado de archivos crudo. |
| 19:40:11–19:40:22 | Ocho clics más en once segundos, los ocho contestando *"ya había una ventana esperando"*. |

El botón funcionó las nueve veces. Lo que faltaba era la dirección, y el
`/vnc.html` al final de ella. Hay un segundo `404` idéntico el 2026-09-22 a las
09:59:51: la trampa se repite sola.

Al mirarlo apareció un segundo problema, **todavía sin ocurrir**. El visor
muestra la pantalla entera, no la ventana de un proveedor. Doyle no serializa:
`abrir(clave)` solo evita reabrir el **mismo** proveedor —`sesiones.py:79`— y
cada uno levanta su propio contexto con su perfil, así que los cuatro Chromium
pueden quedar encimados en `:98`. Y no hay forma de preguntar cuál está al
frente: `GET /api/sesiones` reporta estados, no foco, y en el repo de Doyle no
hay ni un `wmctrl` ni un `xdotool`. Quien teclee la contraseña de LEVIC dentro
del portal de NADRO le entregó una credencial real a un tercero, y eso no se
deshace con un clic: se cambia la contraseña.

## Opciones consideradas

1. **Dejar una frase con la dirección del visor**, sin abrir nada. Es lo mínimo
   y no resuelve el segundo problema.
2. **Embeber el visor en un iframe** dentro de la pantalla de Continental.
3. **Que Doyle cierre la ventana anterior** al abrir otra, garantizando una
   sola desde el módulo.
4. **Que Continental abra el visor en una ventana aparte y se niegue a abrir un
   segundo portal mientras otro espera.**

## Decisión

La 4. El botón abre el visor con `window.open` sobre
`https://doyle.farfanlab.uk/vnc.html`, **deja además el enlace visible**, y la
ruta `POST /api/sesion/{proveedor}/abrir` contesta `ok: false` cuando otro
proveedor está en `abriendo`, nombrándolo y diciendo qué hacer.

## Razones

- **La dirección es configuración y no código.** Vive en `visor_de_doyle` del
  YAML, igual que `a_quien_avisar` y por lo mismo: un hostname escrito en
  Python se encuentra cuando ya falló. Si la llave falta, el botón lo dice.
- **El `/vnc.html` es parte de la decisión, no un detalle.** La raíz devuelve
  un índice de archivos que nadie sabe leer. Ya se midió dos veces.
- **Ventana aparte y no iframe (descarta la 2).** El visor es otro origen y
  está detrás de Access, que manda encabezados que impiden embeberlo; y noVNC
  necesita el teclado en exclusiva, que dentro de un iframe se lo pelea con la
  página que lo contiene — justo donde una contraseña se escribe a medias en el
  lugar equivocado.
- **Popup *más* enlace.** El popup es la ruta buena; un bloqueador lo puede
  impedir sin avisar, y entonces la pantalla volvería a no decir a dónde ir,
  que es la falla de la que nace todo esto. El enlace cuesta un renglón.
- **El candado en Continental y no en Doyle (descarta la 3).** Regla 1 del
  repo: Continental es la cáscara y no le mete lógica a los módulos. Además
  cerrarle la ventana a alguien que ya está tecleando sería peor que no
  abrirla, y la regla se prueba por la costura única que ya existe, con el
  Doyle falso y sin levantar nada.
- **Aquí a `GET /api/sesiones` sí se le cree**, al revés de lo que esta misma
  ruta dice de `guardada`. No es contradicción: `guardada` es un marcador en
  disco que sobrevive a que la sesión caduque —el 2026-09-19 los cuatro decían
  `guardada` con las cuatro caducadas—, mientras que `abriendo` sale del
  diccionario en memoria que `abrir()` acaba de poblar. Uno afirma algo del
  pasado; el otro describe el presente.
- **No poder preguntar no es "no hay nadie esperando".** Si la consulta falla,
  queda en la bitácora con su traza y la pantalla dice que el candado no se
  pudo verificar. Tragársela degradaba el candado en silencio, que es la falla
  muda de la regla 4; lo cazó
  `test_ninguna_falla_de_ningun_borde_lleva_detalles_al_navegador`, no una
  revisión a ojo.

## Consecuencias

- **Abrir los cuatro portales se vuelve una fila, no un paralelo.** Hay que
  entrar en uno, darle a «Ya entré» y seguir con el siguiente. Con un piso
  medido de ~9 s por portal eso no es el cuello de botella, pero es más lento
  que abrir los cuatro de golpe, y el mensaje tiene que dejar claro que es a
  propósito y no una falla.
- **Una sesión abandonada bloquea a las demás.** Si alguien abre LEVIC y se va
  sin confirmar, los otros tres no abren hasta que ese estado se limpie. Hoy la
  salida es confirmar o reiniciar Doyle. **Si esto estorba en la operación
  real, la decisión se revisa** y lo que toca entonces es un modo de descartar
  una ventana abierta desde Continental, no quitar el candado.
- **El candado depende de que Doyle reporte `abriendo` con fidelidad.** Si
  algún día `listar()` dejara de derivarlo del diccionario en memoria, el
  candado quedaría en verde sin proteger nada. Por eso el doble de pruebas se
  ajustó para derivarlo igual que el Doyle real.
- **Queda una dependencia nueva hacia afuera:** la ruta del túnel de
  `doyle.farfanlab.uk`, que vive en el dashboard de Cloudflare y no en este
  repo. Si alguien la borra o la reapunta, el botón manda a una dirección
  muerta y ninguna prueba de aquí se entera.
- **Sigue sin haber forma de saber qué ventana está al frente.** El candado
  hace que la pregunta no haga falta mientras se respete; el día que se quiera
  abrir más de una a la vez, hay que construir esa respuesta primero
  (`wmctrl`/`xdotool` contra `DISPLAY=:98` cruzado con el `--user-data-dir` del
  proceso) y no al revés.
