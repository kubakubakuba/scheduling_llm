FROM python:3.13-slim

RUN pip install --no-cache-dir fastapi uvicorn python-multipart python-dotenv openai httpx jsonschema typer docplex
WORKDIR /workspace
COPY . /workspace

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
