# 10: Descartar un renglón

**Qué construir:** la lista se vuelve trabajable. Como nada se filtra, hay renglones que no se van a pedir, y quitarlos tiene que costar un clic.

**Bloqueado por:** 08.

**Status:** ready-for-agent

- [x] Un clic pone el renglón en `descartado` y sale de la lista de trabajo.
- [x] Los descartados se pueden ver aparte y devolver a `abierto` si fue un error.
- [x] Se ve cuántos renglones se descartaron en el día.
- [x] Queda registrado quién descartó cada renglón: **si se descarta más de la mitad de la lista todos los días, la regla de reposición está mal**, y esa medición es la evidencia para revisarla (condición de revisión del ADR 0002).
