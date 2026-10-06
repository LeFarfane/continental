# 0026 — «Ver en el portal»: mirar el portal de un proveedor desde el panel del artículo

**Fecha:** 2026-10-05  ·  **Estado:** aceptada

## Contexto

En el panel de detalle de un artículo, NADRO a veces dice «no dijo cuántas
tiene»: el portal dio precio pero no una existencia que se pueda leer. La
encargada quiere **ver ella misma** qué dice el portal, y hoy para eso tiene
que ir a buscar el visor, abrir el portal a mano y teclear el código de barras.
Lo mismo pasa con un precio que se ve raro, o con una tarjeta en «sin dato»:
justo donde el sistema no supo, una persona sí puede mirar.

Continental no abre navegadores (regla 1 de `CLAUDE.md`) y las sesiones de los
portales viven en el perfil de Doyle, en atlas. Lo que sí tiene resuelto es
cómo mostrarle a una persona el navegador de atlas: el visor, que «Abrir
sesión» ya abre con `window.open(respuesta.visor, 'visor-doyle')`.

## Decisión (del dueño, 2026-10-05)

1. **Cada una de las cuatro tarjetas de proveedor del panel lleva siempre un
   botón pequeño «Ver en el portal»**, también la que dice «sin dato» y también
   con la lista cerrada (mirar no cambia el pedido).
2. **Continental le pide a Doyle** que abra el portal de ese proveedor con la
   búsqueda del EAN del renglón y lo deje en el visor, y **la pantalla abre el
   visor** en la misma ventana nombrada que «Abrir sesión» (`visor-doyle`), con
   el mismo enlace de respaldo si el navegador la bloquea.
3. **Con la vista abierta, esa tarjeta muestra «Ya vi»**, que le pide a Doyle
   cerrarla. Si Doyle ya la cerró sola por tope, su 404 se trata como ya
   cerrada: sin error.
4. **El EAN lo pone el servidor**, a partir del renglón (`renglon_id`). El
   navegador no manda ningún término: una ruta que buscara en un portal ajeno,
   con la cuenta del dueño, lo que cualquiera escribiera, sería abrirle esa
   cuenta a quien alcance el puerto.
5. **Mirar no guarda nada ni toca la sesión.** Sin tabla nueva, sin firma en la
   base. Sí se registra en la bitácora del servidor quién lo pidió (el correo de
   Access, una firma y no un permiso).
6. **Si el visor muestra un login** (`parece_login` de Doyle), la frase lo dice:
   la sesión de ese proveedor parece caída y en el visor se ve el login.

### Contrato con Doyle

| Llamada | Respuesta |
|---|---|
| `POST /api/ver/{clave}` con `{"termino": "<EAN>"}` | 200 `{ok, ya_abierta, parece_login}`; 404 proveedor desconocido; 409 `{detail}` visor ocupado o proveedor consultando; 400 término vacío |
| `POST /api/ver/{clave}/cerrar` | 200 `{ok}`; 404 si no había vista |
| `GET /api/ver` | `{clave: {termino, abierta_en}}` (no se usa hoy) |

La clave del proveedor es la misma de las sesiones (`nadro`, `levic`, `vicma`,
`quepharma`).

### Rutas de Continental

- `POST /api/proveedor/{clave}/ver` con `{"renglon_id": N}`.
- `POST /api/proveedor/{clave}/ver/cerrar`.

Las dos devuelven `visor` (la dirección de `visor_de_doyle`, o `null`) y
`mensaje` (la frase, compuesta en `vista_del_portal.py`). Un 409 de Doyle sale
como 409 con su `detail`, que Doyle escribe para personas; cualquier otra falla
es «Doyle no responde» con el **tipo** de la excepción y nunca su texto (regla
5). El 409 de Doyle viaja como dato devuelto por el borde (`VisorOcupado`) y no
como excepción: así el cinturón de `test_fallas.py` («de una excepción solo
viaja su tipo») no necesita ninguna excepción para él.

## Opciones consideradas

- **Mostrar el botón solo cuando falta la cantidad** («no dijo cuántas
  tiene»). Se descartó: el dueño decidió que los cuatro siempre. Un botón que
  aparece y desaparece según el dato confunde, y sirve también para revisar un
  precio raro que el sistema sí leyó.
- **Abrir el portal en una pestaña normal del navegador de la persona.** Se
  descartó: las sesiones viven en el perfil de Doyle, en atlas, no en la PC. Un
  portal abierto en la PC pediría login otra vez, con la contraseña del dueño
  tecleada en un navegador cualquiera.
- **Un iframe con el visor dentro del panel.** Se descartó por lo mismo que en
  «Abrir sesión»: el visor vive en otro origen detrás de Cloudflare Access, que
  manda encabezados que impiden embeberlo, y noVNC necesita el teclado en
  exclusiva.
- **Que el navegador mande el término a buscar.** Se descartó (decisión 4).
- **Meter «Ya vi» en la misma tarjeta con un solo botón que alterna.** Se
  descartó: «Ver en el portal» sigue siendo útil con la vista abierta (volver a
  abrir la ventana del visor si se cerró la pestaña), y un botón que cambia de
  significado se aprieta por error.
- **Preguntarle a `GET /api/ver` qué vistas hay abiertas al pintar el panel.**
  Se pospuso: hoy la pantalla recuerda en memoria las vistas que abrió ella, y
  recargar las olvida; volver a darle «Ver en el portal» contesta «ya estaba
  abierto» y la recupera. Se hace si se vuelve molesto.

## Consecuencias

- **Un solo uso del visor a la vez.** El visor muestra la pantalla entera de
  atlas (ADR 0018): una vista abierta lo ocupa, y mientras tanto no se puede
  abrir otra vista ni una sesión (Doyle contesta 409 y la pantalla dice por
  qué). Hay que dar «Ya vi» al terminar; si se olvida, Doyle la cierra sola.
- **El proveedor que se ve no se puede consultar mientras está abierto**
  (Doyle contesta 409 en cualquiera de las dos direcciones). «Volver a
  consultar» o el lote nocturno que lo necesiten esperan a «Ya vi» o al tope.
- La memoria de qué vistas hay abiertas es de cada pestaña; no se comparte
  entre computadoras.
- `ClienteDeDoyle` pasa de once a trece verbos (`ver_en_portal`,
  `cerrar_vista`).
- **Condición de revisión:** si las vistas se quedan abiertas seguido y estorban
  a las consultas, leer `GET /api/ver` al pintar el panel y avisar cuál está
  abierta.
