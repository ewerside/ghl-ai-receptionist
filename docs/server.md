# Server changes

The n8n instance runs with Docker Compose on a small EC2 (t3.micro, 1 GB RAM plus swap), behind Caddy. I made two changes for this project.

## 1. Embedding service

n8n cannot run fastembed, so a small container embeds each question. It joins the compose network and publishes no port, so only n8n can reach it.

```bash
# from a folder with embed/server.py and embed/Dockerfile
sudo docker build -t receptionist-embed .
sudo docker run -d --name receptionist-embed --restart unless-stopped \
  --network <your-compose-network> --memory 400m receptionist-embed
```

The flow calls `http://receptionist-embed:8000/embed` (`EMBED_URL` in `.env`). The container uses about 230 MB.

## 2. Supabase CA for n8n

The Postgres credential checks the server certificate. Supabase signs it with its own root CA, so n8n has to trust that CA.

1. Download `prod-ca-2021.crt` (Supabase dashboard > Database Settings > SSL Configuration).
2. Copy it into the n8n data volume:
   ```bash
   sudo docker cp prod-ca-2021.crt <n8n-container>:/home/node/.n8n/supabase-ca.crt
   ```
3. Add one line to the n8n service environment in `docker-compose.yml`:
   ```yaml
   - NODE_EXTRA_CA_CERTS=/home/node/.n8n/supabase-ca.crt
   ```
4. `sudo docker compose up -d n8n` (n8n is down for a few seconds).

