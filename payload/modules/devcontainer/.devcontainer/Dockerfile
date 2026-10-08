# Sandbox image for coding agents (Claude Code, Codex CLI) working on this project: run them in
# autonomous mode here instead of on the host. Toolbox/tb works the same way as on the host.

# uv version pinned by Toolbox/tb (TB_UV_VERSION).
ARG UV_VERSION=0.12.23
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM debian:13-slim

ARG USERNAME=dev
ARG USER_UID=1000
ARG USER_GID=1000

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git less openssh-client procps ripgrep \
 && rm -rf /var/lib/apt/lists/*

# uv on PATH, so tb does not download its own copy into the (possibly bind-mounted) Runtime/.
COPY --from=uv /uv /uvx /usr/local/bin/

# Non-root user without sudo.
RUN groupadd --gid "${USER_GID}" "${USERNAME}" \
 && useradd --uid "${USER_UID}" --gid "${USER_GID}" --create-home --shell /bin/bash "${USERNAME}"

ENV LANG=C.UTF-8 \
    PATH=/home/${USERNAME}/.local/bin:${PATH} \
    CLAUDE_CONFIG_DIR=/home/${USERNAME}/.claude \
    CODEX_HOME=/home/${USERNAME}/.codex

# Python and caches of the container live in the home directory, apart from the project's
# Runtime/ (on a bind mount it belongs to the host). Toolbox/tb keeps UV_* values that are set.
ENV UV_CACHE_DIR=/home/${USERNAME}/.cache/uv \
    UV_PYTHON_INSTALL_DIR=/home/${USERNAME}/.local/share/uv/python \
    UV_PYTHON_BIN_DIR=/home/${USERNAME}/.local/share/uv/python-bin

USER ${USERNAME}

# Mount points of the named volumes with agent logins (see devcontainer.json); they must exist
# and belong to the user so that new volumes get the same owner.
RUN mkdir -p "/home/${USERNAME}/.claude" "/home/${USERNAME}/.codex" "/home/${USERNAME}/.local/bin"

# Claude Code, native installer: https://code.claude.com/docs/en/setup
RUN curl -fsSL https://claude.ai/install.sh | bash

# Codex CLI, standalone installer: https://github.com/openai/codex#installing-and-running-codex-cli
# The installer keeps program files under CODEX_HOME; point it elsewhere for the install so the
# program stays in the image instead of the ~/.codex volume (which only keeps login and config).
RUN curl -fsSL https://chatgpt.com/codex/install.sh \
    | CODEX_HOME="/home/${USERNAME}/.local/share/codex" CODEX_NON_INTERACTIVE=1 sh
