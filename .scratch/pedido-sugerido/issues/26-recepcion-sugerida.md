# 26: Recepción sugerida

**Qué construir:** que el encargado no tenga que marcar a mano lo que SICAR ya sabe. Cuando la compra se captura, el sistema propone que ese renglón llegó, pero **no lo afirma**.

**Bloqueado por:** 24.

**Status:** ready-for-agent

- [ ] Una función pura recibe los renglones en tránsito y las compras posteriores, y devuelve propuestas con su evidencia: proveedor, producto, cantidad y fecha de la compra.
- [ ] El emparejamiento es por proveedor, producto y fecha posterior al envío. **Nunca por folio**, cuya semántica no está verificada (nadie sabe si es el consecutivo de SICAR o el número de factura del proveedor).
- [ ] El renglón queda **probablemente recibido** y espera un clic; jamás pasa solo a `recibido`.
- [ ] La pantalla muestra en qué se basó la propuesta, para que la persona pueda juzgarla.
- [ ] Confirmar lo pasa a `recibido`; rechazar lo devuelve a `en tránsito`.
- [ ] Con una noche de retraso: la compra aparece en el almacén hasta la cadena siguiente, y eso es normal, no un error.
- [ ] 606 de 3,429 artículos (17.7%) nunca aparecen en compras: para ésos nunca va a haber propuesta, y el marcado manual del ticket 27 es su única salida.
