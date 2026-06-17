FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN pip install --no-cache-dir -e .

CMD ["overnight-app-maker", "--goals", "goals/GOALS.example.md", "--dry-run"]
