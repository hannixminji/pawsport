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

gcloud run jobs create pawsport-backend-bootstrap \
  --image=asia-southeast1-docker.pkg.dev/pawsport-api/pawsport/backend:latest \
  --region=asia-southeast1 \
  --service-account=pawsport-run@pawsport-api.iam.gserviceaccount.com \
  --set-secrets="POSTGRES_URL=POSTGRES_URL:latest,SECRET_KEY=SECRET_KEY:latest,ADMIN_SESSION_SIGNING_SECRET=ADMIN_SESSION_SIGNING_SECRET:latest,ADMIN_PASSWORD=ADMIN_PASSWORD:latest,REDIS_CACHE_URL=REDIS_CACHE_URL:latest" \
  --command="python" \
  --args="-m,scripts.bootstrap" \
  --max-retries=0 \
  --task-timeout=120s \
  --quiet

gcloud run jobs execute pawsport-backend-bootstrap \
  --region=asia-southeast1 \
  --wait



# Tuesday: keep worker warm
gcloud run services update pawsport-backend-worker \
  --region=asia-southeast1 \
  --min-instances=1 \
  --no-cpu-throttling

# After defense: back to zero
gcloud run services update pawsport-backend-worker \
  --region=asia-southeast1 \
  --min-instances=0 \
  --cpu-throttling


Create new GCP project + enable billing
Go to Firebase Console → Add project → link the new GCP project
Firestore → Create database → choose region asia-southeast1
Then run the two deploy commands
  firebase deploy --only firestore:indexes --project=new-project-id
  firebase deploy --only firestore:rules --project=new-project-id






APIs & Services → Credentials → Create Credentials → API Key
Then restrict it:

Click the key → Application restrictions → Android apps
Add your app's package name and SHA-1 fingerprint
Click Save


# Turn on
gcloud run services update pawsport-backend-worker --region=asia-southeast1 --min-instances=1 --no-cpu-throttling

# Turn off
gcloud run services update pawsport-backend-worker --region=asia-southeast1 --min-instances=0 --cpu-throttling
