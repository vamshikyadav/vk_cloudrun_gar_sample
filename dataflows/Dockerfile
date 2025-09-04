FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_PREFER_BINARY=1

# Build toolchain + common headers
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential pkg-config meson ninja-build \
    libffi-dev libssl-dev \
    git curl \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

# 1) Make sure pip/setuptools/wheel are fresh
RUN python -m pip install --upgrade pip setuptools wheel

# 2) Preinstall heavy deps **as wheels** (avoid compiling from source)
#    If any of these tries to build, the step will fail early so you know which one.
RUN pip install --only-binary=:all: \
      "numpy==2.0.1" \
      "pandas==2.2.2" \
      "grpcio==1.65.5"

# 3) Install the rest (these have wheels in normal cases)
RUN pip install --prefer-binary -r requirements.txt

COPY app.py ./app.py

ENV PORT=8080 \
    STREAMLIT_SERVER_PORT=8080 \
    STREAMLIT_SERVER_ENABLECORS=true \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    PROJECT_ID="" \
    DATAFLOW_REGION="us-central1" \
    VERTEX_REGION="us-central1"

EXPOSE 8080
CMD ["bash","-lc","streamlit run app.py --server.port=${PORT} --server.headless=true"]
