# Production deployment (GitHub + Portainer)

Target: `http://192.168.1.108/`.

## Portainer stack

1. Push the repository to a private GitHub repository. Never commit `.env`.
2. In Portainer create a **Git repository** stack and select `docker-compose.yml`.
3. Add the variables from `.env.production.example` in Portainer's environment
   section. Replace both password placeholders; keep `DRY_RUN=true` for the
   first deployment.
4. Deploy the stack. The UI is published on port 80. The backend port is bound
   to server localhost only, and PostgreSQL is not directly published.
5. Check `http://192.168.1.108/api/health`.

Migrations do not run implicitly when the backend restarts. During a normal
server-side maintenance window they can be applied in the backend container:

```sh
alembic upgrade head
```

## Run an Alembic migration from a developer PC

Remote access is deliberately two-sided: the server must open the temporary
gateway and the PC must explicitly permit the migration command.

1. Restrict the server firewall so TCP `${REMOTE_DB_PORT}` is accepted only
   from the developer PC's IP.
2. In the Portainer stack set `COMPOSE_PROFILES=remote-migrations` and
   `ALLOW_REMOTE_DB_MIGRATIONS=true`, keep
   `REMOTE_DB_BIND_ADDRESS=192.168.1.108`, and redeploy. Only the temporary
   gateway exposes PostgreSQL; the database container stays private. The
   recommended external port is `15432`, avoiding conflicts with a PostgreSQL
   instance already listening on the standard port `5432`.
3. On the PC, use a local untracked `.env` containing:

```dotenv
ALLOW_REMOTE_DB_MIGRATIONS=true
REMOTE_DATABASE_URL=postgresql+asyncpg://market_maker:URL_ENCODED_PASSWORD@192.168.1.108:15432/market_maker
```

4. From the repository root run:

```powershell
docker compose --profile tools run --rm --no-deps remote-migrate
```

5. Verify the revision before closing the window:

```powershell
docker compose --profile tools run --rm --no-deps --entrypoint alembic remote-migrate current
```

6. Immediately set `ALLOW_REMOTE_DB_MIGRATIONS=false`, remove
   `COMPOSE_PROFILES` from the Portainer stack, and redeploy. Confirm that
   `192.168.1.108:15432` is no longer reachable.

The flag is checked by both the server gateway and the PC migration container.
The PostgreSQL password is still required. Do not expose either database port to the
internet; prefer an SSH or VPN tunnel when working outside the trusted LAN.

## Updating

Push to GitHub, then use **Pull and redeploy** in Portainer. Apply migrations
before starting code that requires the new schema. Back up the `postgres_data`
volume before destructive schema changes.
