# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py ./

ENV PORT=8080
EXPOSE 8080

CMD ["bash","-lc","streamlit run app.py --server.port=$PORT --server.address=0.0.0.0 --browser.gatherUsageStats=false"]
