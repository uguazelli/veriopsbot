# Veridata Bot

Multi-tenant bot service connecting Chatwoot, RAG, and EspoCRM.

## Stack
- **Python 3.12+**
- **FastAPI**
- **PostgreSQL + AsyncPG**
- **SQLAlchemy 2.0 + FastCRUD**
- **Docker Compose**

## Setup

1. **Environment Variables**:
   Configured in `docker-compose.yml` or `.env`.

2. **Run**:
   ```bash
   docker-compose up --build
   ```

3. **Admin Interface**:
   Visit `http://localhost:4019/admin` to manage Clients, Subscriptions, and Configs.

4. **API Docs**:
   Visit `http://localhost:4019/docs`.

5. **Webhooks**:
   Point Chatwoot webhooks to `http://<your-domain>/webhooks/chatwoot/{client_slug}`.
