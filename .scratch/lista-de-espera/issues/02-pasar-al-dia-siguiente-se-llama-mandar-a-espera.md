# 02: «Pasar al día siguiente» se llama «Mandar a espera»

**What to build:** arreglo previo, **sin cambio de comportamiento**. Todo lo que
la encargada lee sobre el estado `pospuesto` usa el vocabulario nuevo de
`CONTEXT.md`: el botón dice «Mandar a espera», el renglón «En espera», el
bloque «Lista de espera» (o «En espera»), y las frases del servidor dejan de
decir «pasa al día siguiente». El estado en la base sigue llamándose
`pospuesto` (enmienda 2026-10-05 al ADR 0025, punto 1).

**Blocked by:** None (can start immediately)

**Status:** done

- [x] Los botones de la fila y del detalle en Revisar dicen «Mandar a espera»;
      el de devolver dice algo como «Sacar de la espera».
- [x] El título y la frase del bloque de pospuestos usan «espera».
- [x] Las frases del renglón de la lista siguiente dicen «esperaban» en vez de
      «pasaron»: *«se vendieron 2 y esperaban 3, se piden 5»*.
- [x] No cambia ninguna regla: las pruebas existentes de `test_posponer.py`
      siguen pasando, con solo los textos esperados actualizados.
- [x] La columna, el estado y las rutas internas no se renombran.
- [x] La suite completa pasa.
