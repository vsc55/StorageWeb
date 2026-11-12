#!/usr/bin/env bash
# Genera los artefactos de release en dist/:
#   storageweb-<version>-py3-none-any.whl  (pip install, cualquier sistema)
#   storageweb-<version>.zip               (código fuente)
#   storageweb_<version>_<arch>.deb        (Debian/Ubuntu, amd64 y arm64)
#   storageweb-<version>.<arch>.rpm        (RHEL/Rocky/Alma/Fedora/openSUSE, x86_64 y aarch64)
#   SHA256SUMS
#
# Los .deb/.rpm incluyen el wheel de la aplicación y los de sus dependencias, así que se
# instalan sin acceso a Internet (si falta algún wheel, el postinstall recurre a PyPI).
#
# Requisitos: python3 + pip, nfpm (https://nfpm.goreleaser.com/install/)
# Uso:  packaging/build.sh 1.2.3 [amd64 arm64]
set -euo pipefail

VERSION="${1:?Uso: build.sh <version> [arquitecturas...]}"
shift
if [[ $# -gt 0 ]]; then ARCHES=("$@"); else ARCHES=(amd64 arm64); fi
PY_VERSIONS=(3.9 3.10 3.11 3.12 3.13 3.14)

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG="$ROOT/packaging"
BUILD="$ROOT/build/release"
DIST="$ROOT/dist"
cd "$ROOT"

export MAINTAINER="${MAINTAINER:-StorageWeb <storageweb@localhost>}"
export VENDOR="${VENDOR:-StorageWeb}"
export HOMEPAGE="${HOMEPAGE:-https://github.com/}"
export LICENSE="${LICENSE:-Proprietary}"

log() { echo -e "\e[1;34m==>\e[0m $*"; }
render() {  # render <plantilla> <destino> (valores por defecto del paquete)
  sed -e "s#@APP_USER@#storageweb#g" -e "s#@APP_GROUP@#storageweb#g" -e "s#@APP_DIR@#/opt/storageweb#g" \
      -e "s#@CONF_DIR@#/etc/storageweb#g" -e "s#@DATA_DIR@#/var/lib/storageweb#g" \
      -e "s#@STORAGE_DIR@#/srv/storageweb#g" "$1" > "$2"
}

rm -rf "$BUILD" "$DIST"
mkdir -p "$BUILD" "$DIST"

# --------------------------------------------------------------------------- fuentes con versión
log "Preparando fuentes (v$VERSION)"
SRC="$BUILD/storageweb-$VERSION"
mkdir -p "$SRC"
git ls-files -z | xargs -0 -I{} cp --parents {} "$SRC/" 2>/dev/null || \
  cp -r src config packaging tests pyproject.toml README.md .gitignore .gitattributes "$SRC/"
sed -i "s/^__version__ = .*/__version__ = \"$VERSION\"/" "$SRC/src/storageweb/__init__.py"

log "Generando zip de código fuente"
(cd "$BUILD" && python3 -m zipfile -c "$DIST/storageweb-$VERSION.zip" "storageweb-$VERSION")

log "Construyendo el wheel"
python3 -m pip wheel -q --disable-pip-version-check --no-deps --wheel-dir "$DIST" "$SRC"
APP_WHEEL="$(ls "$DIST"/storageweb-"$VERSION"-py3-none-any.whl)"

EXTRA="$BUILD/extra"
mkdir -p "$EXTRA"
render "$PKG/systemd/storageweb.service" "$EXTRA/storageweb.service"
render "$PKG/bin/storageweb-admin" "$EXTRA/storageweb-admin"

# --------------------------------------------------------------------------- deb / rpm
command -v nfpm >/dev/null || { echo "nfpm no está instalado" >&2; exit 1; }

for ARCH in "${ARCHES[@]}"; do
  case "$ARCH" in
    amd64) PYARCH=x86_64;  RPMARCH=x86_64 ;;
    arm64) PYARCH=aarch64; RPMARCH=aarch64 ;;
    *) echo "Arquitectura no soportada: $ARCH" >&2; exit 1 ;;
  esac

  log "Descargando dependencias para linux/$PYARCH"
  WHEELS="$BUILD/wheels-$ARCH"
  mkdir -p "$WHEELS"
  cp "$APP_WHEEL" "$WHEELS/"
  for PY in "${PY_VERSIONS[@]}"; do
    python3 -m pip download -q --disable-pip-version-check --only-binary=:all: \
      --dest "$WHEELS" --implementation cp --python-version "$PY" \
      --platform "manylinux_2_28_$PYARCH" --platform "manylinux_2_17_$PYARCH" \
      --platform "manylinux2014_$PYARCH" \
      "$APP_WHEEL" \
      || echo "   AVISO: faltan wheels para Python $PY/$PYARCH (se usará PyPI al instalar)"
  done

  log "Empaquetando .deb y .rpm ($ARCH)"
  sed -e "s#@VERSION@#$VERSION#g" -e "s#@ARCH@#$ARCH#g" -e "s#@EXTRA@#$EXTRA#g" -e "s#@WHEELS@#$WHEELS#g" \
      -e "s#@MAINTAINER@#$MAINTAINER#g" -e "s#@VENDOR@#$VENDOR#g" \
      -e "s#@HOMEPAGE@#$HOMEPAGE#g" -e "s#@LICENSE@#$LICENSE#g" \
      "$PKG/nfpm.yaml" > "$BUILD/nfpm-$ARCH.yaml"

  nfpm package --config "$BUILD/nfpm-$ARCH.yaml" --packager deb \
       --target "$DIST/storageweb_${VERSION}_${ARCH}.deb"
  nfpm package --config "$BUILD/nfpm-$ARCH.yaml" --packager rpm \
       --target "$DIST/storageweb-${VERSION}.${RPMARCH}.rpm"
done

log "Calculando SHA256SUMS"
(cd "$DIST" && sha256sum -- * > SHA256SUMS)
ls -lh "$DIST"
