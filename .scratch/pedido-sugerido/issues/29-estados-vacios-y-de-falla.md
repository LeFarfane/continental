# 29: Estados vacíos y de falla en la interfaz

**Qué construir:** que la interfaz falle ruidoso. El manejo de errores del servidor está desde el primer commit; lo que falta es que la pantalla diga qué pasó, en lugar de mostrar el vacío, que se lee como una respuesta.

**Bloqueado por:** 28.

**Status:** ready-for-agent

- [ ] Si Doyle no responde, la lista **igual se ve** y dice que los precios no están disponibles, con el motivo.
- [ ] Si el almacén no responde, lo dice con claridad. **Una lista vacía por falla nunca se puede leer como "hoy no se vendió nada".**
- [ ] Un día sin ventas de verdad (el domingo, que la farmacia cierra) se distingue de un fallo de lectura.
- [ ] Ningún error del servidor manda detalles al navegador: el detalle va a la bitácora, al cliente un mensaje genérico. Esto corre detrás de un túnel y un error de base de datos llevaría la cadena de conexión con contraseña.
- [ ] Cada estado de falla dice **qué puede hacer la persona**, o que no hay nada que hacer y a quién avisarle.
