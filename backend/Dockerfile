FROM python:3.13-slim
WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend /app/backend
COPY financial_metrics.py /app/financial_metrics.py
RUN useradd --create-home folio && mkdir /app/.vibe-research && chown folio:folio /app/.vibe-research
USER folio
EXPOSE 8000
CMD ["uvicorn", "backend.server:app", "--host", "0.0.0.0", "--port", "8000"]
