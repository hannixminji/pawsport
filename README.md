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
