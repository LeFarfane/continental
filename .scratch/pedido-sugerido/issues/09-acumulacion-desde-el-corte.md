# 09: La acumulación desde el corte

**Qué construir:** que no se caiga una venta al piso por un día en que nadie abrió la lista. El siguiente pedido sugerido arranca donde cerró el anterior, no en el último día con datos.

**Bloqueado por:** 08.

**Status:** ready-for-agent

- [ ] Un pedido sugerido nuevo incluye todo lo vendido **desde el corte del último cerrado**.
- [ ] La primera vez, cuando no hay cierre anterior, la ventana es de 7 días.
- [ ] El sugerido del lunes incluye las ventas del viernes por la tarde y del sábado completo, que llegan juntas al almacén (peor caso medido: 2.5 días de retraso).
- [ ] Si un día nadie abrió la lista, lo de ese día aparece en la siguiente y no se pierde.
- [ ] Un producto vendido en varios días acumula su cantidad en un solo renglón.
