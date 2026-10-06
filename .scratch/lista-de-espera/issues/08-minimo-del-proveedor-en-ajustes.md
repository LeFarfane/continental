# 08: Mínimo del proveedor en la pestaña Ajustes

**What to build:** una pestaña nueva, **Ajustes**, en la página principal, con
una fila por proveedor conocido: el **mínimo** que pide para surtir, tal como
lo dice el proveedor, y una casilla «incluye IVA». Guardar lo firma quién y
cuándo. Ver `CONTEXT.md` (Mínimo del proveedor), la enmienda 2026-10-05 al ADR
0025 (punto 7) y el spec, historias 32–41.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Migración nueva con una tabla propia: negocio, proveedor, monto, incluye
      IVA, quién, cuándo. Una fila por negocio y proveedor; sin historial. El
      rol `continental` recibe el permiso en la misma migración.
- [ ] Sin fila es «sin mínimo capturado»; cero es «no tiene mínimo». Son
      distintos en la tabla, en la respuesta y en pantalla.
- [ ] La ruta de guardar valida: número, ≥ 0, proveedor conocido (los de la
      correspondencia). Si rechaza, dice por qué; los errores no viajan al
      navegador (regla 5).
- [ ] La firma es el correo de Access (firma, no permiso: regla 3).
- [ ] La pestaña muestra el valor actual con quién y cuándo lo puso.
- [ ] Pruebas: lo guardado (doble, CHECK en Python, SQL como texto), la ruta de
      punta a punta (guardar, sobreescribir, rechazar) y la estática del JS de
      la pestaña. Si se agrega un `fetch`, se actualiza su conteo en las tres
      pruebas que lo fijan.
