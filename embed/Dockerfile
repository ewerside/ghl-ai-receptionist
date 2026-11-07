FROM python:3.11-slim

WORKDIR /app
RUN pip install --no-cache-dir fastembed==0.9.1
ENV FASTEMBED_CACHE=/models
# Download the model at build time, so the container starts without internet access.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/models')"
COPY server.py .

USER nobody
EXPOSE 8000
CMD ["python", "server.py"]
