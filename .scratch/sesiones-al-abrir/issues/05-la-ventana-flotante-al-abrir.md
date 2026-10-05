# 05: La ventana flotante al abrir, y otra vez tras una hora sin uso

**Qué construir:** que lo primero que vea quien abre Continental sean las sesiones. Es una ventana flotante, imagen espejo de la pestaña Sesiones, que se cierra con «Continuar» o con Esc y no impide trabajar. Vuelve a salir cada vez que se abre o se recarga la página, y cuando la pestaña pasa una hora sin un clic ni una tecla. Spec: `../spec.md`. ADR 0024, decisiones 1 y 2.

**Bloqueado por:** ninguno (se puede empezar ya).

**Status:** ready-for-agent

- [x] **Cambio previo:** una sola función pinta las tarjetas de sesión en el contenedor que se le pase, y recibe a quién avisarle cuando un paso termina. La pestaña Sesiones pasa a usarla sin que cambie nada visible. La ventana y la pestaña nunca tienen cada una su copia.
- [x] La ventana es un `<dialog>` modal en el HTML estático, igual que el de confirmar el cierre, con título, las tarjetas y «Continuar». Cuando existan los botones de probar de los tickets 02 a 04, salen en la ventana sin trabajo adicional, por la función compartida.
- [x] Se abre después de la primera carga de la página, también si Doyle no responde: en ese caso muestra el hueco con su motivo, sin tarjetas vacías.
- [x] Se cierra con «Continuar» o con Esc. Al abrirse, el foco entra en ella, y al cerrarse vuelve a donde estaba. Se anuncia como diálogo.
- [x] Si la ventana está abierta, Esc la cierra a ella y no al detalle del renglón.
- [x] Una hora sin clics ni teclas en esa pestaña la vuelve a abrir. El tiempo se cuenta en memoria, sin `localStorage`, así que cada computadora y cada pestaña cuentan por separado. Mientras alguien usa la pantalla, la ventana no aparece.
- [x] Cabe en 375 px sin desplazamiento lateral y respeta la Apariencia (claro, oscuro, auto), con colores solo de `:root`.
- [x] Las pruebas estáticas, al estilo de `test_conciliacion_js.py`, cubren:
  - el `<dialog>` existe;
  - la ventana y la pestaña llaman a la misma función de pintar;
  - existe el contador de una hora, y lo reinician los clics y las teclas;
  - Esc y «Continuar» cierran la ventana.

  `test_pasada_visual.py` sigue pasando.
- [ ] Se verifica a ojo con datos de atlas en claro, en oscuro y a 375 px, con un proxy de solo lectura antes del commit.
