# 05: Lo que espera entra solo al pedido de su proveedor

**What to build:** cuando se arma la lista siguiente, cada renglón que estaba
en espera **nace ya repartido** al pedido en `borrador` de su proveedor, sumado
a lo que se vendió del producto desde entonces, en un solo renglón. Dice la
aritmética y desde cuándo espera. Ver la enmienda 2026-10-05 al ADR 0025
(puntos 2–4) y el spec, «La lista siguiente», historias 20–27.

**Blocked by:** 04

**Status:** done

- [x] Lo que espera se sigue leyendo de la lista **inmediatamente anterior**,
      como hoy lo pospuesto.
- [x] Un renglón con proveedor de la espera nace repartido a ese proveedor: su
      pedido en `borrador` se crea o se reutiliza. La elección lleva la firma
      y la hora de quien lo mandó a espera.
- [x] Sin proveedor de la espera se reparte como hoy.
- [x] Si el producto también se vendió, es un solo renglón con las piezas
      sumadas: *«se vendieron 2 y esperaban 3, se piden 5»*.
- [x] «Desde cuándo» se arrastra y el contador de listas suma 1. Volver a
      mandarlo a espera no cuenta sus piezas dos veces.
- [x] Lo que viene en camino le sigue ganando.
- [x] Si otro proveedor lo da más barato, la tarjeta lo dice como hoy; no se
      cambia solo.
- [x] El renglón muestra «en espera desde el lunes 5 · 3 listas».
- [x] Pruebas: lo puro (suma, contador, herencia de proveedor), el doble, y una
      ruta de punta a punta de varios días (lunes manda, martes aparece
      repartido, martes vuelve a mandar, miércoles cuenta 3: lunes, martes y
      miércoles).
