ARG PYTHON_IMAGE=python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56
FROM ${PYTHON_IMAGE}
ARG PYTHON_IMAGE
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates git build-essential libffi-dev libssl-dev pkg-config libturbojpeg0 ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 --shell /bin/bash vscode
COPY Dockerfile /usr/local/share/hapatchy-Dockerfile
RUN python -c 'import hashlib,json,pathlib,sys; p=pathlib.Path("/usr/local/share"); (p/"hapatchy-image.json").write_text(json.dumps({"base_image":sys.argv[1],"build_inputs":hashlib.sha256((p/"hapatchy-Dockerfile").read_bytes()).hexdigest()}))' "${PYTHON_IMAGE}"
USER vscode
WORKDIR /workspaces/hapatchy
CMD ["bash", "/workspaces/hapatchy/.devcontainer/scripts/entrypoint.sh"]
