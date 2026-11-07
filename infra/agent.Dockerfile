FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df

ARG TARGETARCH
ENV PYTHONUNBUFFERED=1 UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 PATH="/app/agent/.venv/bin:$PATH"
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir uv==0.13.6

# Official pinned release; compare against the checksum obtained from its GitHub release.
RUN test "$TARGETARCH" = amd64 \
    && curl --fail --location --retry 2 --output /tmp/longbridge.tar.gz \
       https://assets.lbkrs.com/github/release/longbridge-terminal/v0.31.1/longbridge-terminal-linux-musl-amd64.tar.gz \
    && echo '78aac9c09f7ebe3b794ff15343378b135568246bf6ca1646efc15c195c1b699a  /tmp/longbridge.tar.gz' | sha256sum --check - \
    && tar -xzf /tmp/longbridge.tar.gz -C /usr/local/bin longbridge \
    && rm /tmp/longbridge.tar.gz \
    && longbridge --version

WORKDIR /app/agent
COPY copilotkit-app/agent/pyproject.toml copilotkit-app/agent/uv.lock copilotkit-app/agent/README.md ./
RUN uv sync --frozen --no-dev
COPY copilotkit-app/agent/src ./src
COPY copilotkit-app/agent/main.py copilotkit-app/agent/alembic.ini ./
COPY copilotkit-app/agent/migrations ./migrations
RUN useradd --create-home --uid 10001 aperture
USER 10001:10001
ENV HOME=/home/aperture
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8123", "--loop", "asyncio"]
