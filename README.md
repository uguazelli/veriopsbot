
# Veri Data

## 0. Prerequisites
- Docker
- Cloudflare account
- DatabaseMart account

## 1. Clone the repository
```bash
git  clone  https://github.com/VeriOps/VeriOps.git
```

## 2. Install Docker

```bash
curl  -fsSL  https://get.docker.com  -o  get-docker.sh && sudo  sh  get-docker.sh
```
#### a. Enable Docker to start on boot
```bash
sudo  systemctl  enable  --now  docker
```
#### b. Add your user to the docker group
```bash
sudo  usermod  -aG  docker  $USER
```
#### c. Allow your user to run Docker (No more sudo docker...)
```bash
sudo  usermod  -aG  docker  $USER
```
#### d. Verify Docker installation
```bash
docker  --version
```
#### e. Verify Docker compose installation
```bash
docker  compose  version
```

## 3. Docker Network

Create a shared network for the containers to communicate
```bash
docker  network  create  veridata.network
```

## 4. Chatwoot

```bash
cd  chatwoot
docker  compose  run  --rm  rails  bundle  exec  rails  db:chatwoot_prepare
docker  compose  up  -d
```

> Visit the URL stored in `FRONTEND_URL`, finish onboarding, and
> generate a bot token.

## 5. Start the bot

```bash
cd  ../vdbot
docker  compose  up  --build  -d
```

## 6. Set DB

#### a. Create tenant
```sql
INSERT INTO tenants ( email, omnichannel_id, crm_id)
VALUES ('admin@veridatapro.com', 1, 1);
```
#### b. After register set as admin
```sql
UPDATE veriops_users
SET is_admin = true
WHERE email = 'admin@veridatapro.com'
```

## 7. Expose local services with Cloudflare Tunnel


#### a. One-off tunnel (quick share)

1. Access Zero trust -> Network -> Tunnels
2. Create anew Tunnul if dosent exists
3. Follow the instruction to install locally as a service
4. Add Published application routes for each port

#### b. Remote server (DatabaseMart VPS)

- Portal: https://console.databasemart.com/
- Server: `server1.veridatapro.com`
- User: `administrator`
- Password: _(see DatabaseMart portal/secret manager)_


### Handy commands

-  `docker compose logs -f <service>` – tail logs for either stack.
-  `docker compose down` – stop and remove containers (volumes persist unless you add `-v`).
-  `docker compose ps` – check service health.



Add the number to the company name to avoid Whatsapp ban

[IMPORTANT] You must enable "Enable Post Username Override" in your Mattermost System Console > Integrations > Integration Management