# 28: La pasada visual

**Qué construir:** hasta aquí la interfaz fue fea a propósito, para que cada rebanada se demostrara por comportamiento. Este ticket es donde el trabajo **es** lo visual: que una tabla de 40 renglones con cuatro precios cada uno se pueda leer sin cansarse, en la pantalla del mostrador y en un teléfono.

**Bloqueado por:** 22 · 23.

**Status:** ready-for-agent

- [ ] Hoja de estilos propia, con los colores declarados como variables en un solo lugar: nada de colores escritos a mano por toda la página.
- [ ] Funciona en claro y en oscuro, con el fondo declarado explícitamente.
- [ ] Densidad pensada para 40+ renglones: la fila tiene que ser compacta sin volverse ilegible, y los números alineados a la derecha.
- [ ] La jerarquía visual dice de un vistazo lo que importa: urgencia, el proveedor más barato, el ahorro, y los huecos (sin dato, sin clasificar, en tránsito) distinguibles **sin depender solo del color**.
- [ ] Sirve en el teléfono: la tabla no obliga a desplazamiento horizontal de la página.
- [ ] Sin cadena de compilación y sin marco de trabajo: HTML, CSS y JavaScript servidos como archivos, igual que Doyle, Marlowe y Max.
- [ ] Las pantallas siguen siendo las mismas: este ticket no cambia comportamiento ni agrega funciones.
