# Deployment Notes

1. Enable PostGIS in Neon

Run this SQL command in your Neon database:

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
```

2. Update Dockerfile

In `ml/Dockerfile`, remove this line:

```
EXPOSE 9000
```

3. Deploy to Cloud Run

Make sure the correct service account is configured.

For the day of the exhibit, set **minimum instances to 1** to prevent cold starts.

```bash
gcloud run deploy <your-service> \
  --service-account=firebase-adminsdk-fbsvc@pawsport-cfd33.iam.gserviceaccount.com \
  --min-instances=1
```

After the exhibit, you may set `--min-instances=0` again to reduce costs.

docker compose up -d
docker compose run --rm bootstrap (For fresh build only)

docker compose logs -f api
docker compose logs -f ml
docker compose logs -f db
docker compose logs -f redis
docker compose logs -f worker

def upgrade() -> None:
    # ── Sequences ─────────────────────────────────────────────────────────────
    op.execute("CREATE SEQUENCE IF NOT EXISTS permission_bit_index_sequence START 1 INCREMENT 1")

    ...

def downgrade() -> None:
    ...

    # ── Sequences ─────────────────────────────────────────────────────────────
    op.execute("DROP SEQUENCE IF EXISTS permission_bit_index_sequence")

docker-compose run --rm bootstrap alembic -c alembic.ini revision --autogenerate -m "add age column to users"

docker-compose run --rm bootstrap alembic -c alembic.ini upgrade head
