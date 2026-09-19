# 12: Consultar el precio de un renglón en Doyle

**Qué construir:** el primer precio real dentro de Continental. El encargado pide la consulta de un renglón y Doyle va a los portales; el precio que vuelve se guarda congelado, con su fecha.

**Bloqueado por:** 01 · 08.

**Status:** ready-for-agent

- [x] Un botón por renglón pide la consulta a Doyle de verdad, contra los cuatro proveedores.
- [x] Doyle no contesta de golpe: devuelve un trabajo y se le pregunta después. La pantalla no se queda colgada esperando (una búsqueda tiene un piso de ~9 s por proveedor y un techo de 60-90 s).
- [x] El precio se guarda **congelado** con el momento de la lectura: un pedido dice a qué precio se decidió, no a cómo está hoy.
- [x] Se guarda también la existencia que reporta el proveedor.
- [x] Si Doyle no responde, el renglón queda sin precio y la pantalla lo dice; **nunca** un cero ni un precio vacío.
- [x] Desarrollado contra el doble de Doyle; demostrado contra el Doyle real, que hoy corre en la torre.

**Sobre la última casilla, con precisión (2026-09-19).** Se hizo UNA búsqueda de
UN producto (EAN `7501349028234`) contra el Doyle real en el 8383, más
`GET /api/sesiones`. Quedó demostrado: que el `job_id` sirve, que los estados
que llegan son los que `_leer_respuesta` espera —y que Doyle emite **`buscando`**
y no `pendiente`, que es lo que obligó a corregir `EstadoDeBusqueda.terminada`—,
y que un portal que no da dato se lee como hueco con su motivo y nunca como
cero. **NO quedó demostrado contra el portal real que una fila con precio se lea
sin perder el `total`**: las cuatro sesiones de Doyle estaban caducadas
(marcadores de agosto) y la búsqueda volvió con los cuatro proveedores en
`error`. Eso se cubre con `test_una_respuesta_real_de_doyle_se_lee_sin_perder_el_total`,
escrito contra la forma exacta que devuelve `buscador.buscar_producto`, y queda
pendiente de repetir cuando alguien abra las sesiones (hilo 1 de `HANDOVER.md`).
