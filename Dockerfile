FROM python:3.12-slim

RUN groupadd -g 1000 htb_agent \
    && useradd -m -u 1000 -g 1000 -s /bin/bash htb_agent

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    android-tools-adb \
    && rm -rf /var/lib/apt/lists/*

USER htb_agent

WORKDIR /htb_agent

RUN curl -LsSf https://astral.sh/uv/install.sh | sh

ENV PATH="/home/htb_agent/.local/bin:${PATH}"

COPY . .

RUN uv venv && \
    uv pip --no-cache-dir install .[anthropic,deepseek,langfuse]

ENTRYPOINT [".venv/bin/htb-agent"]

CMD ["setup"]
