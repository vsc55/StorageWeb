# syntax=docker/dockerfile:1
# Imagen de StorageWeb.
#
#   docker build -t storageweb .
#   docker run -d -p 8080:8080 -v storageweb-data:/data \
#     -e STORAGEWEB_ADMIN_USER=admin -e STORAGEWEB_ADMIN_PASSWORD='cambia-esta-clave' storageweb
#
# Todo lo persistente vive en el volumen /data (config.json, base de datos y archivos).

ARG PYTHON_VERSION=3.13
# Extras de pyproject.toml incluidos en la imagen (vacío = ninguno)
ARG EXTRAS="s3,smb,sftp,azure"

# --------------------------------------------------------------------------- build
FROM python:${PYTHON_VERSION}-slim AS build
ARG VERSION=""
ARG EXTRAS
WORKDIR /src
COPY pyproject.toml README.md ./
COPY src ./src
RUN if [ -n "$VERSION" ]; then \
        sed -i "s/^__version__ = .*/__version__ = \"$VERSION\"/" src/storageweb/__init__.py; \
    fi \
 && pip wheel --no-cache-dir --disable-pip-version-check --wheel-dir /wheels ".${EXTRAS:+[$EXTRAS]}"

# --------------------------------------------------------------------------- runtime
FROM python:${PYTHON_VERSION}-slim
ARG VERSION=""
ARG EXTRAS
LABEL org.opencontainers.image.title="StorageWeb" \
      org.opencontainers.image.description="Servidor web para subir y descargar archivos (usuarios locales y Microsoft Entra ID)" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.licenses="GPL-3.0-or-later"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    STORAGEWEB_CONFIG=/data/config.json

RUN groupadd --system --gid 10001 storageweb \
 && useradd --system --uid 10001 --gid storageweb --home-dir /data --no-create-home \
            --shell /usr/sbin/nologin storageweb \
 && install -d -o storageweb -g storageweb -m 0750 /data

COPY --from=build /wheels /tmp/wheels
RUN pip install --no-cache-dir --disable-pip-version-check --no-index --find-links /tmp/wheels "storageweb${EXTRAS:+[$EXTRAS]}" \
 && rm -rf /tmp/wheels
COPY --chmod=0755 packaging/docker/entrypoint.sh /usr/local/bin/storageweb-entrypoint

USER storageweb
WORKDIR /data
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import os,sys,urllib.request; p=os.environ.get('STORAGEWEB_PORT','8080'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{p}/healthz', timeout=4).status == 200 else 1)"]

ENTRYPOINT ["storageweb-entrypoint"]
CMD ["serve"]
