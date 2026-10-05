FROM python:3.12-slim

# Evitar generación de archivos .pyc y buffer de salida
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

WORKDIR /app

# Instalar dependencias del sistema mínimas
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copiar manifiesto e instalar dependencias
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copiar código fuente
COPY src/ /app/src/

# Crear directorio de datos para SQLite local o caché
RUN mkdir -p /app/data

# Puerto expuesto para comunicación interna con el admin panel
EXPOSE 8000

# Comando de arranque por defecto: servidor FastAPI
CMD ["uvicorn", "eros.api:app", "--host", "0.0.0.0", "--port", "8000"]
