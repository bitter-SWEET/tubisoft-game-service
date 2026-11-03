FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends openssl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 tubisoft \
    && useradd --uid 10001 --gid tubisoft --no-create-home tubisoft \
    && install -d -m 0700 -o tubisoft -g tubisoft /state
WORKDIR /app
COPY pyproject.toml README.md LICENSE THIRD_PARTY_NOTICES.md ./
COPY src/ ./src/
RUN python -m pip install --no-cache-dir .
USER 10001:10001
VOLUME ["/state"]
EXPOSE 8080/tcp 30000/tcp 30000/udp 30001/tcp 30002/udp
CMD ["tubisoft-server"]
