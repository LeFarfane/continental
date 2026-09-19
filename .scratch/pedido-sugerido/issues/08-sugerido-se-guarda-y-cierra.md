# 08: El sugerido se guarda y se cierra

**Qué construir:** la lista deja de recalcularse cada vez que se abre la página. Se guarda con su corte, y el encargado puede darla por cerrada cuando ya pidió lo que iba a pedir.

**Bloqueado por:** 04 · 07.

**Status:** ready-for-agent

- [x] Al abrir el día se crea el pedido sugerido si no existe, y si existe se lee: **nunca se duplica** para el mismo día y negocio.
- [x] Estados de la lista: `abierto` → `cerrado` → `vencido`.
- [x] Cerrar una lista guarda hasta qué momento de ventas consideró.
- [x] Una lista de un día anterior que quedó con renglones sin atender queda `vencida`, no `abierta` para siempre.
- [x] La lista guarda cuándo se armó, y eso se ve en la pantalla.
