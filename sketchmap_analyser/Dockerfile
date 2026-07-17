# Use an official Python runtime as a parent image
FROM python:3.8.20

# Set environment variables
ENV PYTHONUNBUFFERED 1

# Build metadata injected by CI (.github/workflows/registry-build-publish.yml);
# shown as the version badge in the UI. Empty in local dev builds.
ARG GIT_TAG=""
ARG GIT_SHA=""
ARG GIT_COMMIT_DATE=""
ENV GIT_TAG=$GIT_TAG
ENV GIT_SHA=$GIT_SHA
ENV GIT_COMMIT_DATE=$GIT_COMMIT_DATE

# RUN mkdir /app

# Set the working directory
WORKDIR /app

COPY requirements.txt /app/
# # Copy the current directory contents into the container at /app
# COPY . /app

RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/
# # Define the command to run on container start
# CMD ["python", "manage.py", "makemigrations"]

# Expose the port the app will run on
EXPOSE 8000


# CMD ["python", "manage.py", "runserver", "localhost:8000"]

# Default command to run your Django app
CMD ["bash", "-c", "python manage.py migrate && python manage.py runserver 0.0.0.0:8000"]