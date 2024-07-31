FROM python:3.11

COPY . /app

WORKDIR /app

RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver

RUN pip install -r req.txt

CMD ["python", "main.py"]