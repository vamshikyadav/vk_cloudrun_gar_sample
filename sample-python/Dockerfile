FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
ENV PORT=8080
CMD ["gunicorn", "-b", "0.0.0.0:8080", "app:app"]
