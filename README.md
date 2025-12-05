# VD-RevOps Stack

A lightweight RevOps playground that pairs Chatwoot, an n8n automation canvas, and a FastAPI retrieval bot (`veriopsbot`). Each service lives in its own folder and can be started independently, but the defaults are wired so they can talk to each other out of the box.

## Stack overview

- `chatwoot/` – Dockerised Chatwoot (Rails + Sidekiq) pointed at your own Postgres instance.
- `veriopsbot/` – FastAPI app that syncs knowledge files, answers Chatwoot conversations, and optionally triggers n8n.

## Requirements

- Docker Engine 24+ with the Compose plugin
- `git`
- Access to a Postgres instance (local or managed) for both Chatwoot and the bot

## Environment files

Before running any service, edit the `.env` files that already live in each directory.

### `chatwoot/.env`

| Variable                | Why it matters                                                                                  |
| ----------------------- | ----------------------------------------------------------------------------------------------- |
| `SECRET_KEY_BASE`       | Rails signed cookies; generate with `rake secret` for production.                               |
| `FRONTEND_URL`          | External URL Chatwoot advertises (set to your domain or `http://localhost:3000`).               |
| `POSTGRES_*`            | Connection info to the Postgres instance you manage (defaults point to `host.docker.internal`). |
| `MAILER_*` / `SMTP_*`   | Needed if you plan to send invitations or alerts by email.                                      |
| `ENABLE_ACCOUNT_SIGNUP` | Flip to `false` or `api_only` to lock down self‑serve accounts.                                 |

Leave the rest at their defaults unless you need social logins, S3 storage, or other optional integrations.

### `veriopsbot/.env`

| Variable                             | Why it matters                                                                                                |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------- |
| `POSTGRES_*`                         | Where the bot persists state/embeddings. Point it to the same DB host as above or another managed database.   |
| `N8N_EDITOR_BASE_URL`, `WEBHOOK_URL` | URLs the bot uses when it triggers n8n workflows. Keep them in sync with the ports you expose.                |
| `GENERIC_TIMEZONE`                   | Default timezone for n8n.                                                                                     |
| `RAG_SOURCE_DIR`                     | Folder (inside the repo) where uploaded documents are stored. Bound to your host via Docker so files persist. |

### Runtime overrides (`docker-compose.yml`)

- `CHATWOOT_BOT_ACCESS_TOKEN` – token generated in Chatwoot for the automation bot user.
- `CHATWOOT_API_URL` – usually `http://localhost:3000/api/v1` for local work; point to your public Chatwoot domain in production.
- `N8N_BASE_URL` – base URL the bot uses for webhook calls (mirror `WEBHOOK_URL` unless you expose it differently).

## Local quick start

1. **Clone the repo**
   ```bash
   git clone <repo-url>
   cd VeriOps
   ```
2. **Configure env files** – Update `chatwoot/.env` and `veriopsbot/.env` with your Postgres creds, URLs, and secrets.
Create a shared network for the containers to communicate
```bash
docker network create veridata.network
```
3. **Start Chatwoot**
   ```bash
   cd chatwoot
   docker compose run --rm rails bundle exec rails db:chatwoot_prepare
   docker compose up -d
   ```
   Visit the URL stored in `FRONTEND_URL`, finish onboarding, and generate a bot token.
4. **Start the bot + n8n**
   ```bash
   cd ../veriopsbot
   export CHATWOOT_BOT_ACCESS_TOKEN=<token-from-chatwoot>
   docker compose up --build
   ```
   FastAPI runs at `http://localhost:8080`; n8n lives at `http://localhost:5678`.

## Set DB

```sql
INSERT INTO tenants ( email, omnichannel_id, crm_id)
VALUES ('admin@veridatapro.com', 1, 1);
```
### After register set as admin
```sql
UPDATE veriops_users
SET is_admin = true
WHERE email = 'admin@veridatapro.com'
```


## Handy commands

- `docker compose logs -f <service>` – tail logs for either stack.
- `docker compose down` – stop and remove containers (volumes persist unless you add `-v`).
- `docker compose ps` – check service health.

## Expose local services with Cloudflare Tunnel

### One-off tunnel (quick share)

1. Access Zero trust -> Network -> Tunnels
2. Create anew Tunnul if dosent exists
3. Follow the instruction to install locally as a service
4. Add Published application routes for each port

## Remote server (DatabaseMart VPS)

- Portal: https://console.databasemart.com/
- Server: `server1.veridatapro.com`
- User: `administrator`
- Password: _(see DatabaseMart portal/secret manager)_

## Ubuntu Docker bootstrap (root or sudo user)

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo \
"deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
$(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | \
sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update

sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker run hello-world   # smoke test
```

If `systemctl status docker` shows the service inactive, start it manually with `sudo systemctl start docker`.

---

That’s it—edit the env files when you switch environments and you can spin each component up or down independently. Once both stacks are live, Chatwoot hands conversations to `veriopsbot`, which reads docs from `RAG_SOURCE_DIR` and can call n8n through the URLs you set locally or through Cloudflare when exposed.
