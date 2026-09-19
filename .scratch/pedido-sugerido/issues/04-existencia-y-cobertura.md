# 04: Existencia, días de cobertura y orden por urgencia

**Qué construir:** la lista deja de ser una enumeración y se vuelve legible: cada renglón dice cuánto queda en el anaquel y cuántos días duraría, y lo que se va a acabar primero aparece arriba.

**Bloqueado por:** 03.

**Status:** ready-for-agent

- [x] Cada renglón muestra la existencia actual del producto.
- [x] Cada renglón muestra sus días de cobertura.
- [x] La lista viene ordenada por urgencia: agotado primero, luego menor cobertura.
- [x] **Nada se filtra por cobertura.** Un producto con anaquel lleno aparece igual, solo más abajo: filtrar sería meter la lógica de la tarjeta O2 por la puerta de atrás, y el dueño pidió explícitamente no usarla.
- [x] La existencia y la cobertura que se muestran son las del momento en que se propuso el renglón.
