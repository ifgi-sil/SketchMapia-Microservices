FROM python:3.12.15-bookworm
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt

ENV PYTHONDONTWRITEBYTECODE=1

COPY . /app/
EXPOSE 8006
CMD ["bash", "-c", "python manage.py migrate && python manage.py runserver 0.0.0.0:8006"]