FROM python:3.13-slim

# The runner launches disposable worker containers through the mounted Docker
# socket. The Debian Docker daemon package is not needed here; docker-cli is
# sufficient and keeps the runner image smaller. Compose runs this service as
# root; disposable workers still run as the restricted non-root user below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends docker-cli nodejs npm \
    && rm -rf /var/lib/apt/lists/* \
    && command -v docker \
    && docker --version

RUN pip install --no-cache-dir fastapi uvicorn docplex networkx pandas plotly
WORKDIR /opt/app
COPY analysis/worker_entry.py /opt/sandbox/worker_entry.py
COPY analysis/applet_worker.mjs /opt/sandbox/applet_worker.mjs
COPY analysis/applet-package.json /opt/sandbox/package.json
RUN cd /opt/sandbox && npm install --omit=dev --ignore-scripts --no-audit --no-fund
COPY analysis /opt/app/analysis
COPY solver.py /opt/app/solver.py

RUN useradd --uid 65532 --create-home --shell /usr/sbin/nologin worker
USER 65532:65532

CMD ["uvicorn", "analysis.runner_service:app", "--host", "0.0.0.0", "--port", "9100"]
