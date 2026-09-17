# One image, several roles (ingestion job, ML service, public API, experiments).
# CPU-only PyTorch keeps the image portable; GPU training is done on the host
# (see README "Reproducing results").
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN pip install --upgrade pip \
 && pip install torch==2.14.0 --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY configs ./configs
COPY src ./src
COPY experiments ./experiments
COPY dashboard ./dashboard
COPY pytest.ini ./

# data/, cache/ and results/ are bind-mounted by docker-compose.
EXPOSE 8000 8001
CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
