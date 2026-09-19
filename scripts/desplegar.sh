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
# El orden importa, y es el del ticket 16:
#   1. pull        — trae el código
#   2. compila     — TODOS los módulos, incluido iniciar.py; si uno no
#                    compila, ni se intenta lo demás
#   3. pruebas     — el suite completo, con el venv real de atlas
#   4. reinicia    — solo si 2 y 3 pasaron; si el servicio estaba en `failed`
#                    por el límite de reinicios, primero se limpia
#   5. verifica    — que contesta por HTTP, por la misma interfaz y el mismo
#                    puerto a los que apunta el túnel
#
# `set -e` sale al primer comando que falla, `-u` convierte una variable sin
# definir en un error en vez de en una cadena vacía, y `-o pipefail` es el que
# de verdad importa aquí: sin él, `algo_que_falla | tail -1` devuelve cero y el
# script seguiría hasta reiniciar.

set -euo pipefail

cd "$(dirname "$0")/.."
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

paso "1/5  git pull"
if ! git remote | grep -q .; then
    echo "    !! este repo no tiene ningún remoto configurado."
    echo "       Al 2026-09-19 Continental todavía no tiene remoto de git; está"
    echo "       en la lista de HANDOVER.md. Configúralo antes de desplegar:"
    echo "         git remote add origin <url>"
    exit 1
fi
git -c pull.rebase=true pull -q
git log --oneline -1

paso "2/5  compilan todos los módulos"
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

paso "3/5  pruebas (el suite completo, con el venv de atlas)"
if ! "$PYTHON" -m pytest -q > "$SALIDA_PRUEBAS" 2>&1; then
    echo "    !! el suite falló. NO se reinicia nada; el servicio sigue como estaba."
    tail -25 "$SALIDA_PRUEBAS"
    exit 1
fi
tail -1 "$SALIDA_PRUEBAS"

paso "4/5  reinicio de $SERVICIO"
if [[ "$(systemctl is-active "$SERVICIO" || true)" == "failed" ]]; then
    echo "    estaba en 'failed' (límite de reinicios): se limpia primero"
    sudo systemctl reset-failed "$SERVICIO"
fi
sudo systemctl restart "$SERVICIO"

paso "5/5  que quedó vivo, por HTTP"
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

paso "listo"
