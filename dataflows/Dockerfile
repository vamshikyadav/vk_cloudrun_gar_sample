# Base
FROM python:3.11-slim

# System deps (clean, minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# App code
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./app.py

# Streamlit server config for Cloud Run (port 8080, headless)
ENV PORT=8080
ENV STREAMLIT_SERVER_PORT=8080
ENV STREAMLIT_SERVER_ENABLECORS=true
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Optional: pass defaults via env (override at deploy)
ENV PROJECT_ID=""
ENV DATAFLOW_REGION="us-central1"
ENV VERTEX_REGION="us-central1"

# Expose for local runs (Cloud Run ignores EXPOSE, but fine)
EXPOSE 8080

# Entry
CMD ["bash", "-lc", "streamlit run app.py --server.port=${PORT} --server.headless=true"]
