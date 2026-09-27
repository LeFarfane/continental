# Propuesta — por qué caduca la sesión de LEVIC, y qué hacer

**Fecha:** 2026-09-27  ·  **Estado:** abierta, espera al dueño  ·  **Rama:** `investigar-sesion-levic`

No es un ADR todavía. Es lo que se pudo averiguar sin tocar el portal ni la
base, lo que falta medir, y las salidas con lo que cuesta cada una. No se tocó
código de Continental ni de Doyle.

El ADR 0019 ya evita el daño (el lote se niega a correr con una sesión
muerta). Esto es la otra mitad, la que pide el pendiente *"volver a armar
continental-lote.timer"*: saber **por qué** muere la sesión.

---

## 1. Lo que se midió esta noche

Del archivo de cookies que guarda Doyle en atlas
(`~/proyectos/Doyle/data/sesiones/levic.json`, solo nombres y fechas, nunca
los valores), escrito por última vez el 2026-09-26 a las 22:23:

| Cookie | Caduca |
|---|---|
| `ASP.NET_SessionId` | **sin fecha** (cookie de sesión) |
| `cookiesession1` | 2027-09-21 (balanceador, no es login) |
| `_ga`, `_gid`, `_gcl_au`, `twk_*`, `TawkConnectionTime` | analítica y chat |

**LEVIC no tiene cookie de autenticación con fecha.** No hay `.ASPXAUTH` ni
nada parecido. Todo el login de LEVIC cuelga de `ASP.NET_SessionId`, que es
solo una llave: lo que dice "este usuario ya entró" vive **en el servidor de
LEVIC**, no en la cookie.

Compárese con los otros tres, que sí aguantaron el 26:

| Proveedor | Cookie de login | Caduca |
|---|---|---|
| NADRO | `VtexIdclientAutCookie_nadro` | 2026-09-27 13:04 |
| VICMA | `.FocusPointSap.Authentication` | 2026-10-07 10:26 |
| QuePharma | `.ASPXAUTH` | 2026-09-27 22:00 |
| **LEVIC** | **ninguna** | — |

Del journal de Doyle (`journalctl -u doyle`), el 2026-09-26:

| Hora | Hecho |
|---|---|
| 10:23 | Se abre LEVIC desde el visor (dato del pendiente). |
| 13:05 | Hay una búsqueda (queda un aviso de QuePharma) y **LEVIC no se queja**. |
| 19:14 | Primera `[levic] la sesión se ve caída`. |
| 19:58–20:45 | El lote, con LEVIC caída en cada renglón. |
| 22:23 | Se reabre LEVIC (lo dice la fecha de `levic.json`). |

Doyle no escribe nada en el journal cuando una búsqueda sale bien, así que a
las 13:05 **no se puede afirmar** que LEVIC estuvo en esa búsqueda. Si estuvo,
la sesión aguantó 2 h 42 min sin uso y murió en algún punto de las 6 h 09 min
siguientes.

## 2. Hipótesis descartadas

- **"La cookie caduca por fecha del lado del navegador."** No hay cookie de
  login con fecha que pueda caducar. Descartada con el archivo en la mano.
- **"Chrome tira la cookie de sesión al cerrarse."** Es el problema que el
  ADR 0006 de Doyle ya resolvió: `ASP.NET_SessionId` **está** en
  `levic.json`, y el puente la reinyecta en cada consulta. Además, entre las
  13:05 y las 19:14 Doyle no se reinició. Descartada.

## 3. La que queda

**El servidor de LEVIC olvida la sesión.** Las dos formas comunes en un sitio
ASP.NET WebForms, sin poder distinguirlas todavía:

1. **Por inactividad.** El `sessionState` de ASP.NET tiene un plazo que se
   renueva con cada visita (20 min si nadie lo cambió; si la de las 13:05
   contó, LEVIC lo tiene bastante más largo). Si es esto, **una visita cada
   tanto la mantiene viva sin teclear nada.**
2. **Porque el servidor se reinicia** (reciclaje del sitio en IIS, un
   despliegue suyo). La sesión en memoria se pierde a cualquier hora, se use
   o no. Si es esto, ninguna visita la salva.

La prueba que las separa es la consulta de la sección 4: si **todos** los
huecos que la mataron son más largos que **todos** los que aguantó, es
inactividad y el límite está entre los dos.

## 4. Lo que falta medir (necesita al dueño)

**a) Lo que ya está en la base.** Cada visita del lote y del botón de
completar quedó en `pedidos.precio_de_proveedor` con su hora y su motivo. Una
consulta de solo lectura saca los huecos sin uso, ordenados, con "aguantó" o
"la mató":

```bash
cd ~/proyectos/Continental
docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
    -v proveedor=levic < sql/consultas/cuanto-aguanta-la-sesion.sql
```

No se pudo correr esta noche: el agente nocturno no tiene permiso de leer la
base de producción. La consulta **no se ha ejecutado nunca**; si truena, es
error de la consulta y no de los datos.

**b) Un experimento barato, gratis desde mañana.** La sesión se reabrió el 26
a las 22:23. La primera búsqueda de LEVIC de la mañana del 27 es una medición
de ~10 h sin uso. Si contesta, la hipótesis de inactividad pierde fuerza (o el
límite es enorme); si caduca, se suma a la tabla.

**c) Si hace falta el número exacto.** Abrir la sesión y buscar un producto
de LEVIC a los 30 min, luego esperar 1 h, luego 2 h, luego 4 h — cada búsqueda
reinicia la cuenta, así que el hueco se dobla cada vez. La primera que caduque
da el límite entre ese hueco y el anterior. Son cuatro o cinco búsquedas en un
día de trabajo.

## 5. Salidas, según lo que salga

| | Qué es | Sirve si… | Costo |
|---|---|---|---|
| **A. Mantenerla viva** | Doyle visita la página de catálogo de LEVIC cada N min (N = la mitad del límite medido), sin buscar nada | es inactividad | Un robot que tiene la sesión del dueño abierta todo el día. Choca con el punto 3 del ADR 0001 de Doyle ("entrar como entra una persona"). **Lo decide el dueño.** |
| **B. Abrirla tarde** | La sesión se abre a mano poco antes de las 22:00 | el límite es mayor que el hueco hasta el lote | Depende de que alguien esté a esa hora. Frágil. |
| **C. Correr sin LEVIC** | La sonda del ADR 0019 deja fuera a LEVIC y el lote corre con tres | ninguna otra sale | Justo lo que el ADR 0019 evita: LEVIC es el que le gana a NADRO. |
| **D. Lote temprano para LEVIC** | Consultar solo LEVIC justo después de abrir la sesión | es reinicio del servidor | La lista de la noche no existe hasta las 20:30; habría que partir el lote en dos. |

**Recomendación:** medir primero (4a basta si la base tiene suficientes
huecos). Si sale inactividad, **A** con N conservador es lo único que devuelve
el lote nocturno sin nadie mirando; es una decisión de principio y no técnica,
por eso no se escribió código. Si sale reinicio del servidor, ninguna salida
es buena y **B** es la menos mala.

**Qué no se tocó:** ni el portal de LEVIC (ninguna visita de prueba esta
noche), ni la base, ni el código de Doyle o Continental.
