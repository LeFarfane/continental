# 07: Aviso al cerrar de lo que volvió de la espera

**What to build:** al cerrar una lista, a mano o sola, el aviso de lo que se
perdería lleva un grupo nuevo: los renglones **abiertos** que trajeron piezas
de la espera y nadie pidió ni volvió a mandar a espera. Se van a dar por
atendidos (ADR 0020) y reabrir deja de servir en cuanto se arma la lista
siguiente; el aviso lo dice. Lo que **está** en espera al cerrar sigue fuera
del aviso. Ver la enmienda 2026-10-05 al ADR 0025 (punto 5) y el spec,
historias 28–31.

**Blocked by:** 05

**Status:** ready-for-agent

- [ ] Un renglón abierto con piezas de la espera se señala al cerrar, con sus
      piezas y desde cuándo esperaba.
- [ ] La frase dice que reabrir deja de servir cuando se arma la lista
      siguiente.
- [ ] Un renglón en espera al cerrar no se señala.
- [ ] El cierre automático no cambia de comportamiento: da por atendido igual
      que hoy; lo nuevo es solo que se diga.
- [ ] Pruebas: lo puro en el mismo lugar que hoy prueba lo que se perdería, y
      una ruta de punta a punta que cierra con un renglón que volvió de la
      espera.
