# Python version
FROM python:3.12-slim-bookworm

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    gettext \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements/ /app/requirements/
RUN pip install --no-cache-dir -r requirements/dev.txt

# Copy project
COPY . /app/

# Make scripts executable
RUN chmod +x /app/docker/celery/entrypoint.sh

# Default command (can be overridden)
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
