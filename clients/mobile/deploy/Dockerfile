FROM ghcr.io/astral-sh/uv:0.7-python3.12-bookworm-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src/ ./src/
RUN uv sync --frozen --no-dev --extra browser
# The complete reviewed customized snapshot has priority over the upstream source.
COPY customization/packages/ /opt/octop-custom/
ENV PYTHONPATH=/opt/octop-custom OCTOP_CUSTOM_BUILD=1 OCTOP_HOME=/data/octop OCTOP_BIND_HOST=0.0.0.0 OCTOP_PORT=8088
VOLUME ["/data/octop"]
EXPOSE 8088
ENTRYPOINT ["/app/.venv/bin/python", "-m", "octop", "run", "--host", "0.0.0.0", "--port", "8088"]
