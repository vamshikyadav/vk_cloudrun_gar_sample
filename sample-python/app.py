from fastapi import FastAPI
import os

app = FastAPI()

@app.get("/")
def root():
    return {"message": "Hello from Cloud Run!"}

@app.get("/health")
def health():
    return {"status": "ok"}
