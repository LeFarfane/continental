# 19: Motivos del hueco, botón de completar y latido

**Qué construir:** que el encargado pueda arreglar solo lo que falló de noche, y que el dueño se entere si el lote no corrió. El silencio es el modo de falla que de verdad muerde.

**Bloqueado por:** 18.

**Status:** ready-for-agent

- [ ] La pantalla distingue tres motivos distintos: el lote se cortó por tiempo, el portal no contestó, la sesión caducó.
- [ ] Un botón vuelve a consultar solo los precios que faltan, sin lanzar el lote completo.
- [ ] Si una sesión caducó, la pantalla lo dice con el botón que la abre, sin tener que entrar a otra aplicación.
- [ ] Latido a Uptime Kuma al terminar bien, con **monitor propio**, distinto del de la cadena de ventas y del de Marlowe: si compartieran monitor, una noche sin lote no avisaría nada.
- [ ] Si falla el latido, la corrida **no** se aborta: marcar como rota una corrida buena es peor que perderse un latido.
