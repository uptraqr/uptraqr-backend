from fastapi import FastAPI

app = FastAPI(
    title="Uptraqr",
    description="Uptime monitoring platform for local businesses",
    version="0.1.0"
)

@app.get("/")
def root():
    return {
        "name": "Uptraqr",
        "status": "running",
        "version": "0.1.0"
    }

@app.get("/health")
def health():
    return {"status": "healthy"}
