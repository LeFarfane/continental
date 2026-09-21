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
# El orden importa, y es el del ticket 16, más el último paso del ticket 17,
# más el paso 4 del ADR 0017:
#   1. pull        — trae el código
#   2. compila     — TODOS los módulos, incluido iniciar.py; si uno no
#                    compila, ni se intenta lo demás
#   3. pruebas     — el suite completo, con el venv real de atlas
#   4. forma       — que la base tenga cada columna que este código nombra,
#                    leída como el rol (`continental.verificar --forma`, ADR
#                    0017). Va ANTES del reinicio y lo DETIENE si no cuadra:
#                    es la pregunta "¿este código puede correr contra esta
#                    base?", y con la respuesta equivocada la lista del día
#                    rebota con `column ... does not exist`. Nombra la
#                    migración exacta que falta, con su comando.
#   5. reinicia    — solo si 2, 3 y 4 pasaron; si el servicio estaba en
#                    `failed` por el límite de reinicios, primero se limpia
#   6. vive        — que contesta por HTTP, por la misma interfaz y el mismo
#                    puerto a los que apunta el túnel
#   7. verifica    — los invariantes sobre los DATOS de producción
#                    (`continental.verificar`, ticket 17). Va AL FINAL y no
#                    antes: los pasos 1 a 6 dicen si el código quedó bien
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
# Esta misma ruta, absoluta y antes del `cd`: el paso 1 la compara antes y
# después del pull para saber si hay que relanzarse (ver más abajo).
YO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
cd "$RAIZ"
export PYTHONPATH="${PYTHONPATH:-$PWD/src}"

# La MISMA interfaz que declara la unidad de systemd. Si se recreó la red
# `borde` y el gateway cambió, este `curl` del paso 6 falla y lo dice, que es
# justo lo que se quiere: el detalle y cómo arreglarlo están en
# docs/decisiones/0005-continental-escucha-en-el-gateway-de-borde.md.
export CONTINENTAL_HOST="${CONTINENTAL_HOST:-172.19.0.1}"
PUERTO="${CONTINENTAL_PUERTO:-8585}"
PYTHON=.venv/bin/python
SERVICIO=continental-web.service
SALIDA_PRUEBAS="$(mktemp)"
trap 'rm -f "$SALIDA_PRUEBAS"' EXIT

paso() { printf '\n==> %s\n' "$*"; }

# SI ESTE MISMO ARCHIVO CAMBIÓ CON EL PULL, SE VUELVE A LANZAR — medido.
#
# El 2026-09-21 el commit `37abad2` pasó este script de seis pasos a siete (el
# de la forma de la base, ADR 0017). El dueño lo corrió en atlas y la salida
# fue, textual salvo los rótulos, que aquí se escriben con palabras para no
# confundir a las pruebas que cuentan los pasos:
#
#     ==> 1 de 6  git pull
#         rama: main
#     37abad2 (HEAD -> main, ...) Mezcla verificar-forma-base...
#     ==> 2 de 6  compilan todos los módulos
#     ...
#     ==> 4 de 6  reinicio de continental-web.service
#
# El pull trajo la versión de siete pasos y **corrió la de seis**: bash ya
# tenía abierto el archivo viejo (git no lo reescribe, lo reemplaza por otro,
# y bash sigue leyendo del que abrió). O sea que el filtro de la forma, que
# existe justo para impedir un reinicio contra la base equivocada, no corrió
# en el despliegue que lo traía. Y pasa CADA VEZ que cambia este archivo: el
# primer despliegue con el cambio corre sin el cambio.
#
# Y este arreglo no se salva de sí mismo: el despliegue que TRAE esta
# función lo corre todavía una versión que no la tiene. Ese primero hay que
# correrlo dos veces; de ahí en adelante, ya no.
#
# El arreglo: guardar el hash de este archivo antes del pull, compararlo
# después y, si cambió, `exec` de la versión nueva con los mismos argumentos.
#
# SIN BUCLE: el relanzamiento exporta CONTINENTAL_DESPLEGAR_RELANZADO=1, y con
# esa variable puesta el script NO vuelve a hacer `git pull` (el código ya es
# el que trajo el pull de la versión anterior) y por tanto no tiene nada que
# comparar ni motivo para relanzarse. Se eligió saltar el pull y no "jalar
# otra vez pero sin relanzarse": un segundo pull podría traer OTRA versión de
# este archivo, y se correría la vieja sin decirlo — la misma trampa, de
# vuelta. Consecuencia: si alguien exporta esa variable a mano en su sesión,
# el despliegue deja de jalar. El paso 1 lo dice en voz alta cuando pasa.
#
# POR QUÉ UNA FUNCIÓN Y UNA SOLA LÍNEA QUE LA LLAMA — no "simplificar".
#
# Bash no lee un script entero antes de correrlo: lee un comando, lo ejecuta,
# lee el siguiente. Lo que haya en el archivo DESPUÉS del pull se lee de disco
# cuando ya pasó el pull. Hoy git reemplaza el archivo (otro inodo) y bash
# sigue leyendo el viejo, que es la trampa de arriba; si algún día el archivo
# se reescribiera en su lugar, bash leería el nuevo desde la posición en bytes
# del viejo: media línea de una versión pegada a media línea de la otra.
#
# Por eso el pull, la comparación y el `exec` viven los tres dentro de esta
# función, que bash termina de leer ENTERA antes de ejecutar nada de ella, y
# se llaman desde UNA línea del paso 1. Si el archivo no cambió, lo que se lee
# después es idéntico y da igual de dónde venga; si cambió, el `exec` ocurre
# sin que bash lea ni un byte más de este archivo. Sacar el pull de la función
# y dejar la comparación "justo abajo" parece lo mismo y no lo es: esa
# comparación la estaría leyendo bash del archivo que el pull acaba de tocar.
#
# `bash "$YO"` y no `"$YO"` a secas: el `exec` no depende de que la versión
# nueva conserve el bit de ejecución (ya se perdió una vez, commit `00f79e0`).
# `$YO` es la ruta ABSOLUTA de este archivo, calculada arriba junto a `RAIZ`
# y ANTES del `cd`: da igual si se invocó por ruta absoluta, relativa o por
# `ssh ... '~/...'`.

actualizar_y_relanzarse() {
    if [[ -n "${CONTINENTAL_DESPLEGAR_RELANZADO:-}" ]]; then
        echo "    sin git pull: esta es la versión que trajo el pull de la corrida"
        echo "    anterior (CONTINENTAL_DESPLEGAR_RELANZADO=$CONTINENTAL_DESPLEGAR_RELANZADO)"
        return 0
    fi
    local antes despues
    antes="$(git hash-object --no-filters "$YO")"
    git -c pull.rebase=true pull -q
    despues="$(git hash-object --no-filters "$YO")"
    if [[ "$antes" != "$despues" ]]; then
        paso "desplegar.sh cambió con este pull: me vuelvo a lanzar con la versión nueva"
        # `exec` no corre el `trap ... EXIT`: el temporal se borra a mano.
        rm -f "$SALIDA_PRUEBAS"
        export CONTINENTAL_DESPLEGAR_RELANZADO=1
        exec bash "$YO" "$@"
    fi
}

paso "1/7  git pull"
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
# Pull, comparación y relanzamiento en UNA línea: ver `actualizar_y_relanzarse`.
actualizar_y_relanzarse "$@"
echo "    rama: $(git rev-parse --abbrev-ref HEAD)"
git log --oneline -1

# AVISO, NO FALLA: alguna rama remota va por delante de lo que se despliega.
#
# El 2026-09-20 atlas estaba en `main` mientras todo el trabajo iba en
# `pedido-sugerido`. `git pull` bajó los objetos, movió `origin/pedido-sugerido`
# y contestó **"Already up to date"** — que era cierto para `main` y falso para
# lo que la persona quería desplegar. Los seis pasos salieron verdes sobre
# código de antier y lo único que lo delataba era el commit de esta línea, que
# es justo lo que se lee de reojo.
#
# No puede fallar duro: desplegar `main` mientras una rama de trabajo va
# adelante es legítimo y es lo normal a media semana. Lo que no es legítimo es
# que no se diga.
adelantadas=""
for rama in $(git for-each-ref --format='%(refname:short)' refs/remotes/origin | grep -v '/HEAD$' || true); do
    cuantos="$(git rev-list --count "HEAD..$rama" 2>/dev/null || echo 0)"
    if [[ "$cuantos" -gt 0 ]]; then
        adelantadas="${adelantadas}       $rama va $cuantos commit(s) adelante"$'\n'
    fi
done
if [[ -n "$adelantadas" ]]; then
    echo "    !! hay ramas remotas por delante de lo que se está desplegando:"
    printf '%s' "$adelantadas"
    echo "       No detiene nada. Pero si esperabas esos cambios, NO están aquí."
fi

paso "2/7  compilan todos los módulos"
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

paso "3/7  pruebas (el suite completo, con el venv de atlas)"
if ! "$PYTHON" -m pytest -q > "$SALIDA_PRUEBAS" 2>&1; then
    echo "    !! el suite falló. NO se reinicia nada; el servicio sigue como estaba."
    tail -25 "$SALIDA_PRUEBAS"
    exit 1
fi
tail -1 "$SALIDA_PRUEBAS"

paso "4/7  la base tiene la forma que este código espera"
# LA FORMA, NO LOS DATOS, Y POR ESO VA AQUÍ Y NO AL FINAL (ADR 0017).
#
# Los invariantes del paso 7 no deben impedir que un código bueno llegue. Esto
# es otra pregunta: si falta una columna que el código nombra, el código NO es
# bueno para esta base, y reiniciar cambiaría un servicio que funciona por uno
# que rebota. Las migraciones solo agregan, así que el código anterior sigue
# sirviendo con la base migrada: el orden correcto es migrar y después
# desplegar, y este paso lo hace cumplir.
#
# La trampa que no se puede tapar desde aquí: el pull del paso 1 YA dejó el
# código nuevo en disco. El servicio web sigue con el viejo en memoria, pero
# el lote de las 22:00 arranca de disco. Por eso el lote revisa la forma por
# su cuenta y se niega a correr (`forma.antes_del_lote`), y el mensaje lo dice
# para que nadie lo descubra por el monitor.
if ! "$PYTHON" -m continental.verificar --forma; then
    echo ""
    echo "    !! NO se reinicia nada; el servicio sigue con el código anterior."
    echo "       El código nuevo YA está en disco (paso 1): el lote de las 22:00"
    echo "       lo ve, y se va a negar a correr (latido rojo) hasta que la base"
    echo "       cuadre. Corre arriba las migraciones que se nombran, con"
    echo "       credenciales de dueño, y vuelve a correr este script."
    exit 1
fi

paso "5/7  reinicio de $SERVICIO"
if [[ "$(systemctl is-active "$SERVICIO" || true)" == "failed" ]]; then
    echo "    estaba en 'failed' (límite de reinicios): se limpia primero"
    sudo systemctl reset-failed "$SERVICIO"
fi
sudo systemctl restart "$SERVICIO"

paso "6/7  que quedó vivo, por HTTP"
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

paso "7/7  invariantes sobre los datos de producción"
# `if !` en vez de dejar que `set -e` lo mate, para poder explicar QUÉ falló.
# Un paso 7 rojo no quiere decir que el despliegue haya salido mal: el código
# ya está puesto y el servicio ya contestó en el paso 6. Lo que está mal son
# los datos, y quien lo lea tiene que saber la diferencia antes de intentar
# deshacer un despliegue que no hace falta deshacer.
if ! "$PYTHON" -m continental.verificar; then
    echo ""
    echo "    !! el CÓDIGO quedó desplegado y el servicio está arriba (paso 6)."
    echo "       Lo que falla son los DATOS. Arriba está cada falla con el"
    echo "       comando que la repara; esto señala y no repara a propósito."
    exit 1
fi

paso "listo"
