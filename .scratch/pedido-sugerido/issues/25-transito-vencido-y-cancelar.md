# 25: Tránsito vencido y cancelar un pedido

**Qué construir:** la válvula de escape. Un renglón en tránsito que nunca llega se queda fuera de la lista para siempre, y eso es mercancía que va a faltar sin que nadie lo note.

**Bloqueado por:** 24.

**Status:** ready-for-agent

- [ ] Un renglón que lleva más de N días en tránsito se señala como vencido, con el número de días a la vista. N se configura, no va escrito en el código.
- [ ] Un pedido que nunca se capturó se puede cancelar, y sus renglones vuelven a `abierto` para el siguiente sugerido.
- [ ] Cancelar queda firmado con quién y cuándo.
- [ ] Un renglón en tránsito vencido se puede devolver a la lista uno por uno, sin cancelar el pedido completo.
