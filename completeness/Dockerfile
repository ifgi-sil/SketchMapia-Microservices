# Use an official Python runtime as a parent image
FROM python:3.12.15-bookworm

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Set the working directory
WORKDIR /app

# Install dependencies before copying application code.
COPY requirements.txt /app/

RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt

ENV PYTHONDONTWRITEBYTECODE=1

COPY . /app/

# Expose the port the app will run on
EXPOSE 8002

# Define the command to run on container start
# CMD ["python", "manage.py", "makemigrations"]
# CMD ["python", "manage.py", "migrate"]

# Default command to run your Django app
CMD ["bash", "-c", "python manage.py migrate && python manage.py runserver 0.0.0.0:8002"]