FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bots ./bots
COPY tests ./tests
RUN useradd -m bot && chown -R bot /app
USER bot
CMD ["python", "-m", "bots.booking"]
