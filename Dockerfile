FROM python:3.12-slim

WORKDIR /app

# Install runcible (including the webui extras) from the source tree.
COPY setup.py requirements.txt README.md ./
COPY runcible ./runcible

RUN pip install --no-cache-dir .

# Datasource is provided at runtime via -m/--mergedb-database, -y/--yaml, or
# the MERGEDB_DATABASE/RUNCIBLE_YAML environment variables. See
# runcible/webui/cli.py for the full set of options.
ENV RUNCIBLE_WEBUI_HOST=0.0.0.0
ENV RUNCIBLE_WEBUI_PORT=8080

EXPOSE 8080

ENTRYPOINT ["runcible-webui"]
