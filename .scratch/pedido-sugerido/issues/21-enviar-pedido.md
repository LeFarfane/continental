# 21: Enviar un pedido

**Qué construir:** el momento en que el pedido deja de ser un borrador y se convierte en algo que el sistema tiene que recordar. Marcarlo como enviado es lo que después evita pedir doble.

**Bloqueado por:** 20.

**Status:** ready-for-agent

- [ ] Antes de enviar se ve el total en pesos del pedido, para saber cuánto se va a comprometer.
- [ ] `borrador` → `enviado`, con quién lo envió y cuándo, firmado con el correo que verificó Access.
- [ ] Un pedido `enviado` ya no se edita.
- [ ] Al enviar, sus renglones pasan a `en tránsito`.
- [ ] La pantalla deja claro que enviar significa "yo ya lo capturé en el portal del proveedor", no que Continental se lo mandó a nadie: **Continental no hace pedidos en los portales** (fuera de alcance del ADR 0002).
