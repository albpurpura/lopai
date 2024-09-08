FROM python:3.10

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY static ./static
COPY main.py .
COPY documents/ ./documents/

CMD ["python", "main.py"]