#!/usr/bin/env bash
#
# Despliega Continental en atlas y COMPRUEBA que quedó vivo. Un solo comando.
#
#   ssh -t eddie@192.168.100.14 '~/proyectos/Continental/scripts/desplegar.sh'
#
# El `-t` es para que `sudo` pueda pedir la contraseña en tu terminal: este
# script corre como eddie y solo el reinicio del servicio necesita root.
#
# POR QUÉ EXISTE
# ---------------
# El 2026-09-08 Marlowe desplegó un `app.py` que no compilaba. El servicio
# entró en bucle de reinicio y el dueño estuvo corrigiendo enlaces contra un
# servidor que no existía. El flujo era "git pull, reinicia, y ojalá": nada
# comprobaba nada, y las 148 pruebas de aquel repo pasaban -ninguna importaba
# el módulo de la web-. Este script hace lo mismo que se hacía a mano, pero se
# detiene en el primer paso que falla y lo dice ANTES de reiniciar un servicio
# que estaba funcionando.
#
# El orden importa, y es el del ticket 16 más el paso 6 del ticket 17:
#   1. pull        — trae el código
#   2. compila     — TODOS los módulos, incluido iniciar.py; si uno no
#                    compila, ni se intenta lo demás
#   3. pruebas     — el suite completo, con el venv real de atlas
#   4. reinicia    — solo si 2 y 3 pasaron; si el servicio estaba en `failed`
#                    por el límite de reinicios, primero se limpia
#   5. vive        — que contesta por HTTP, por la misma interfaz y el mismo
#                    puerto a los que apunta el túnel
#   6. verifica    — los invariantes sobre los DATOS de producción
#                    (`continental.verificar`, ticket 17). Va AL FINAL y no
#                    antes: los pasos 1 a 5 dicen si el código quedó bien
#                    desplegado, y éste dice si lo que hay en la base está
#                    sano. Son preguntas distintas y la segunda no tiene por
#                    qué impedir que un código bueno llegue a atlas — pero sí
#                    tiene que salir con código distinto de cero, o nadie la
#                    mira. Señala y no repara: cada falla trae el comando.
#
# `set -e` sale al primer comando que falla, `-u` convierte una variable sin
# definir en un error en vez de en una cadena vacía, y `-o pipefail` es el que
# de verdad importa aquí: sin él, `algo_que_falla | tail -1` devuelve cero y el
# script seguiría hasta reiniciar.

# SE EJECUTA, NO SE IMPORTA — y el freno no es paranoia, es de lo medido.
#
# El 2026-09-20 alguien escribió `. desplegar.sh` estando dentro de `scripts/`,
# que es donde más natural sale escribirlo. Lo que pasó, eslabón por eslabón:
# importado, `$0` vale `-bash` y no la ruta del script; `dirname -bash` contesta
# *invalid option*; la sustitución queda vacía; `cd "/.."` aterriza en `/` **sin
# fallar**, así que `set -e` no tiene nada que detener; y `git` contesta que eso
# no es un repositorio. El script culpó entonces al remoto —que existe desde el
# 2026-09-19— y su `exit 1`, al estar importado, salió del shell de la sesión:
# se cayó la conexión de ssh.
#
# `return` antes que `exit` justamente por eso: dentro de un script importado,
# `exit` mata el shell de quien lo importó. Si no se pudo `return` —porque no
# estamos importados— entonces sí, `exit`.
#
# **Y VA ANTES DE `set -euo pipefail`, que es el eslabón que falta a la vista.**
# Importado, el `set -e` no se queda en este archivo: se le pega al shell de la
# sesión. Con él puesto, un `return 1` limpio ya es un comando que devolvió
# distinto de cero en ese shell, y `set -e` lo mata igual — la conexión de ssh
# se cae lo mismo, solo que ahora con el mensaje correcto impreso antes. Medido
# el 2026-09-20 con el freno ya escrito: seguía cerrando el shell.
#
# Así que el orden es la mitad del arreglo. Si alguien sube estas líneas por
# debajo del `set`, el freno sigue pareciendo bueno y deja de servir.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
    echo "desplegar.sh se ejecuta, no se importa. Usa:" >&2
    echo "    ~/proyectos/Continental/scripts/desplegar.sh" >&2
    echo "o desde la torre:" >&2
    echo "    ssh -t eddie@192.168.100.14 '~/proyectos/Continental/scripts/desplegar.sh'" >&2
    return 1 2>/dev/null || exit 1
fi

set -euo pipefail

# `BASH_SOURCE` y no `$0`, por lo mismo de arriba. Y el `cd` va dentro de la
# sustitución para que un fallo al resolver la raíz sea un fallo y no un viaje
# silencioso a `/`.
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"
export PYTHONPATH="${PYTHONPATH:-$PWD/src}"

# La MISMA interfaz que declara la unidad de systemd. Si se recreó la red
# `borde` y el gateway cambió, este `curl` del paso 5 falla y lo dice, que es
# justo lo que se quiere: el detalle y cómo arreglarlo están en
# docs/decisiones/0005-continental-escucha-en-el-gateway-de-borde.md.
export CONTINENTAL_HOST="${CONTINENTAL_HOST:-172.19.0.1}"
PUERTO="${CONTINENTAL_PUERTO:-8585}"
PYTHON=.venv/bin/python
SERVICIO=continental-web.service
SALIDA_PRUEBAS="$(mktemp)"
trap 'rm -f "$SALIDA_PRUEBAS"' EXIT

paso() { printf '\n==> %s\n' "$*"; }

paso "1/6  git pull"
# DOS PREGUNTAS DISTINTAS, DOS MENSAJES DISTINTOS. Antes había uno solo, y el
# 2026-09-20 contestó "no tienes remoto" a un "no estás en un repositorio". El
# remoto existía desde el día anterior, así que el mensaje mandó a arreglar algo
# que no estaba roto mientras el problema real quedaba sin nombrar. Un
# diagnóstico seguro de sí mismo señalando el lugar equivocado es lo mismo que
# hacía el `[MAL]` falso del verificador: enseña a desconfiar de la herramienta.
if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "    !! $PWD no es un repositorio de git."
    echo "       El script se ubica solo, así que llegar aquí quiere decir que"
    echo "       el clon no está donde se espera. Debería ser:"
    echo "         ~/proyectos/Continental"
    exit 1
fi
if ! git remote | grep -q .; then
    echo "    !! este repo no tiene ningún remoto configurado."
    echo "       Debería tener 'origin' apuntando al GitHub privado:"
    echo "         git remote add origin git@github.com:LeFarfane/continental.git"
    exit 1
fi
git -c pull.rebase=true pull -q
git log --oneline -1

paso "2/6  compilan todos los módulos"
"$PYTHON" - <<'PY'
import ast, pathlib

# `src/**/*.py` MÁS `iniciar.py`. Ese último no lo importa nadie y es
# exactamente el archivo que el servicio ejecuta: dejarlo fuera sería repetir
# el hueco que este paso viene a cerrar.
mods = sorted(pathlib.Path("src").rglob("*.py"))
arranque = pathlib.Path("iniciar.py")
if arranque.exists():
    mods.append(arranque)

for m in mods:
    ast.parse(m.read_bytes(), filename=str(m))
print(f"    {len(mods)} módulos compilan")
PY

paso "3/6  pruebas (el suite completo, con el venv de atlas)"
if ! "$PYTHON" -m pytest -q > "$SALIDA_PRUEBAS" 2>&1; then
    echo "    !! el suite falló. NO se reinicia nada; el servicio sigue como estaba."
    tail -25 "$SALIDA_PRUEBAS"
    exit 1
fi
tail -1 "$SALIDA_PRUEBAS"

paso "4/6  reinicio de $SERVICIO"
if [[ "$(systemctl is-active "$SERVICIO" || true)" == "failed" ]]; then
    echo "    estaba en 'failed' (límite de reinicios): se limpia primero"
    sudo systemctl reset-failed "$SERVICIO"
fi
sudo systemctl restart "$SERVICIO"

paso "5/6  que quedó vivo, por HTTP"
SALUD="http://$CONTINENTAL_HOST:$PUERTO/api/salud"
for i in $(seq 1 15); do
    sleep 1
    if curl -sf -m 3 "$SALUD" | grep -q '"ok":[[:space:]]*true'; then
        echo "    arriba en ${i}s — $SALUD"
        break
    fi
    if [[ $i -eq 15 ]]; then
        echo "    !! no contestó en 15s en $SALUD"
        echo "       Si la unidad está 'active (running)' y esto igual falla, lo"
        echo "       más probable es que el gateway de la red \`borde\` cambió:"
        echo "       docker network inspect borde --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}'"
        systemctl status "$SERVICIO" --no-pager -n 12 || true
        exit 1
    fi
done

paso "6/6  invariantes sobre los datos de producción"
# `if !` en vez de dejar que `set -e` lo mate, para poder explicar QUÉ falló.
# Un paso 6 rojo no quiere decir que el despliegue haya salido mal: el código
# ya está puesto y el servicio ya contestó en el paso 5. Lo que está mal son
# los datos, y quien lo lea tiene que saber la diferencia antes de intentar
# deshacer un despliegue que no hace falta deshacer.
if ! "$PYTHON" -m continental.verificar; then
    echo ""
    echo "    !! el CÓDIGO quedó desplegado y el servicio está arriba (paso 5)."
    echo "       Lo que falla son los DATOS. Arriba está cada falla con el"
    echo "       comando que la repara; esto señala y no repara a propósito."
    exit 1
fi

paso "listo"
