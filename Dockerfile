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

# Comando de arranque por defecto: modo daemon 24/7
CMD ["python", "-m", "eros.main", "--daemon"]
