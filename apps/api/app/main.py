from fastapi import FastAPI

app = FastAPI(title="chess-coach api", version="0.0.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
