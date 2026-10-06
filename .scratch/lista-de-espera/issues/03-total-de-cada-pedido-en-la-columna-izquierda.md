# 03: El total en dinero de cada pedido en la columna izquierda

**What to build:** en la pantalla de captura, la columna «Pedidos de esta
lista» dice el total en dinero de cada pedido junto a lo que ya decía:
*«NADRO · $1,661.94 · 0 de 9»*. Es la **misma cifra** del botón «Enviar» de ese
pedido, calculada por el servidor con la misma función; el navegador solo la
pinta. Ver el spec, «El total por pedido», historias 1–6.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [x] La respuesta de la captura trae el total de cada pedido, calculado por la
      misma función que la cifra de «Enviar» (no una segunda suma).
- [x] Los renglones sin precio no se suman como cero: el total los dice aparte
      («$1,200 + 2 sin precio»).
- [x] Los renglones descartados y en espera no cuentan.
- [x] El total se actualiza cuando cambia el pedido (descartar, devolver,
      ajustar cantidad) sin recargar la página.
- [x] Sigue a la vista cuántos renglones van tachados.
- [x] Pruebas: lo puro (total con y sin precios faltantes), la ruta de punta a
      punta, y una estática del JS que fija que la columna pinta el total del
      servidor y no lo suma en el navegador.
