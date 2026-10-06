# 09: El aviso del mínimo en Captura

**What to build:** en la pantalla de captura, junto al total de cada pedido, se
ve su mínimo y si llega: *«faltan $260 para el mínimo de NADRO»*. Es un
**aviso, no un bloqueo**: «Enviar» sigue funcionando. Sin mínimo capturado dice
«sin mínimo capturado» en gris y no avisa. Ver el spec, «El mínimo del
proveedor y Ajustes», historias 35–38.

**Blocked by:** 03, 08

**Status:** ready-for-agent

- [ ] La comparación la hace el **servidor**, en la base del mínimo: si incluye
      IVA, el total se lleva a con-IVA con la misma función que ya usa el
      puente. Nunca se restan dos cifras en bases distintas.
- [ ] Viaja ya como estado y frase: `llega`, `no llega` (con lo que falta) o
      `sin mínimo capturado`. Un mínimo de cero siempre llega.
- [ ] Con renglones sin precio, el aviso lo dice en vez de dar por buena una
      suma incompleta.
- [ ] El aviso tiene «Mandar a espera» a la mano (el botón del ticket 06 si ya
      existe).
- [ ] Pruebas: lo puro (con y sin IVA, sin mínimo, cero, sin precios), la ruta
      de punta a punta y la estática del JS (pinta la frase del servidor y no
      compara en el navegador).
