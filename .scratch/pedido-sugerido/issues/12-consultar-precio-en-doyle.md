# 12: Consultar el precio de un renglón en Doyle

**Qué construir:** el primer precio real dentro de Continental. El encargado pide la consulta de un renglón y Doyle va a los portales; el precio que vuelve se guarda congelado, con su fecha.

**Bloqueado por:** 01 · 08.

**Status:** ready-for-agent

- [ ] Un botón por renglón pide la consulta a Doyle de verdad, contra los cuatro proveedores.
- [ ] Doyle no contesta de golpe: devuelve un trabajo y se le pregunta después. La pantalla no se queda colgada esperando (una búsqueda tiene un piso de ~9 s por proveedor y un techo de 60-90 s).
- [ ] El precio se guarda **congelado** con el momento de la lectura: un pedido dice a qué precio se decidió, no a cómo está hoy.
- [ ] Se guarda también la existencia que reporta el proveedor.
- [ ] Si Doyle no responde, el renglón queda sin precio y la pantalla lo dice; **nunca** un cero ni un precio vacío.
- [ ] Desarrollado contra el doble de Doyle; demostrado contra el Doyle real, que hoy corre en la torre.
