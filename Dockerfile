# Dockerfile para Trading Bot API (FastAPI + Binance + Firebase)
# Imagen base ligera de Python 3.10
FROM python:3.10-slim

# Establecer directorio de trabajo dentro del contenedor
WORKDIR /app

# Copiar el archivo de requisitos y instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código fuente del proyecto
COPY . .

# Exponer el puerto 8000 para la aplicación FastAPI
EXPOSE 8000

# Comando por defecto para iniciar la aplicación con Uvicorn
CMD ["python", "-m", "uvicorn", "api_bot:app", "--host", "0.0.0.0", "--port", "8000"]