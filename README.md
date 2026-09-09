# Signal Slate

Check dialogue problems before the next take. Signal Slate helps a film sound team inspect a sample rehearsal, review a suggested microphone setting change, approve it, and check whether the repeat rehearsal improved.

The current application uses **simulated microphone receivers and a 12-second synthetic dialogue clip**. In cloud mode, Gemini investigates the readings and Grafana Cloud stores the measurements used to check the result. It does not analyze uploaded audio or operate physical microphones.

## Using Signal Slate

1. **Scene:** choose the sample and click **Check sound**.
2. **Sound:** listen to the marked problem and click **Find a fix**.
3. **Change:** enter any restrictions, confirm the interpreted rule, review the suggestion and click **Test this change**.
4. **Compare:** listen to **Before** and **After**, then open the report. If the change failed, request another suggestion when available.
5. **Report:** review the checks, open the Grafana readings or download the report.

The microphone selector changes which receiver's simulated sound faults you hear. All microphones share the same sample dialogue; selecting a name does not isolate that actor's voice. A healthy microphone, or an unsuccessful correction, can sound identical before and after. Only one version plays at a time.

A successful result means the simulated rehearsal passed the application's checks. Incomplete readings produce an inconclusive result; a change that leaves the problem unresolved remains failed. Neither result is presented as a successful fix.

Cloud mode calls Gemini and Grafana. **Preview without cloud** uses sample data without contacting either service. Opening a page, checking setup or reading a saved report does not call Gemini. Grafana links require access to the configured Grafana stack.

## Hosting

The root `Dockerfile` builds the React frontend and Python API into **one container listening on port 8000**. Supply your existing PostgreSQL database through `DATABASE_URL`; no database container is created.

| Container setting | Value |
| --- | --- |
| Dockerfile | `Dockerfile` |
| Build context | Repository root |
| Application port | `8000` |
| Public URL | Your HTTPS domain |
| Health check | HTTP `GET /ready` on port `8000` |
| Health check start period | `90` seconds |
| Instances | `1` |

Use an HTTPS reverse proxy to forward requests to the application port. The container serves the frontend and `/api` from the same domain, so no separate frontend or API URL is needed. The image includes its startup command and automatically applies database migrations.

### Required runtime settings

Supply these as container environment variables at runtime. Keep credentials out of build arguments; this image does not require secrets to build.

```dotenv
DATABASE_URL=postgresql://APP_USER:URL_ENCODED_PASSWORD@DB_HOST:5432/APP_DATABASE?sslmode=require
SIGNAL_SLATE_ALLOWED_ORIGINS=https://YOUR_DOMAIN
SIGNAL_SLATE_SECURE_COOKIES=true
SIGNAL_SLATE_RUNTIME_ENABLED=false
```

- Use a dedicated application database on your existing PostgreSQL server. PostgreSQL 17 is the tested version. The database user needs permission to create and update the application's tables. The container automatically applies pending migrations before serving requests.
- Use your database provider's TLS settings and allow connections from the VPS. URL-encode special characters in the database password. `postgres://`, `postgresql://` and `postgresql+psycopg://` URLs are accepted.
- Set the allowed origin to the exact public HTTPS origin, with no trailing slash or path. If you serve multiple domains, list their origins separated by commas. Wildcards are not supported.
- Keep secure cookies enabled for HTTPS. This setting works behind an HTTPS reverse proxy without trusting client-supplied forwarding headers.
- `SIGNAL_SLATE_RUNTIME_ENABLED=false` permits preview only. Set it to `true` after adding the Google and Grafana configuration below.

### Google and Grafana

For cloud checks, add:

```dotenv
GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
GOOGLE_CLOUD_LOCATION=global
GOOGLE_GENAI_USE_VERTEXAI=true
GEMINI_MODEL=gemini-2.5-flash
GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/google/credentials.json

GRAFANA_URL=https://YOUR_STACK.grafana.net
GRAFANA_SERVICE_ACCOUNT_TOKEN=YOUR_READ_TOKEN
GRAFANA_PROMETHEUS_DATASOURCE_UID=YOUR_PROMETHEUS_DATASOURCE_UID
GRAFANA_LOKI_DATASOURCE_UID=YOUR_LOKI_DATASOURCE_UID
GRAFANA_OTLP_ENDPOINT=https://YOUR_OTLP_GATEWAY/otlp
GRAFANA_STACK_ID=YOUR_STACK_ID
GRAFANA_LOKI_PUSH_URL=https://YOUR_LOGS_ENDPOINT/loki/api/v1/push
GRAFANA_LOGS_TENANT_ID=YOUR_LOGS_TENANT_ID
GRAFANA_TELEMETRY_WRITE_TOKEN=YOUR_METRICS_AND_LOGS_WRITE_TOKEN

MAX_SESSIONS_PER_DAY=20
MAX_MODEL_TURNS_PER_WORKFLOW=5
MAX_OUTPUT_TOKENS=1024
SIGNAL_SLATE_RUNTIME_ENABLED=true
```

Provide a Google runtime identity authorized to call Gemini in the configured project, with the `aiplatform.googleapis.com` API enabled. On a VPS, mount its credential configuration as a read-only file at the path above using a read-only bind mount. The application runs as UID **10001**; this user must be able to read the file and traverse its parent directories. With workload identity federation, mount any additional files referenced by the credential configuration too. If using a service-account key, use a dedicated application identity and keep the key only on the server. Your laptop's `gcloud` login is not automatically available on the VPS.

Copy the Grafana endpoints and IDs from your own stack. The read token must permit querying the metrics and logs data sources; the separate telemetry token needs metrics and logs write access. The application includes the Grafana query client in its image.

Do not put credential files in the repository, Docker image or browser configuration. The UI reports whether configuration is present; a completed cloud rehearsal is needed to verify actual provider access.

The application enforces a maximum of 20 live sessions per UTC day and five model turns per workflow; the environment settings may lower these limits. Output tokens are bounded separately. These are usage controls, not a currency spending cap.

### After deployment

1. Open `/ready`: it must return HTTP 200 with `{"status":"ok"}`. This checks PostgreSQL without calling Google or Grafana.
2. Open the landing page and `/rehearsal`. Refreshing a rehearsal or report URL should retain the page.
3. Complete a preview to check the workflow and playback.
4. After configuring cloud access, complete a cloud check and open its saved Grafana readings. A failed suggested correction is a valid result; provider errors or missing evidence need investigation.

Sessions and reports are stored in PostgreSQL. Browser access is tied to a cookie and expires after 24 hours; download reports you need to retain. Back up the application database before upgrades. Keep one application instance while migrations run automatically during startup. The current application needs no writable application volume; PostgreSQL holds its persistent state, and sample audio is bundled in the image.

## Run with Docker

Docker Engine and Docker Compose are required, along with access to the existing PostgreSQL database.

```bash
cp .env.example .env
# Edit .env with your database URL and the settings described above.
# For local HTTP only, use:
# SIGNAL_SLATE_ALLOWED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080
# SIGNAL_SLATE_SECURE_COOKIES=false
# SIGNAL_SLATE_RUNTIME_ENABLED=false
chmod 600 .env
docker compose up --build -d
```

Open `http://localhost:8080`. The optional Compose file runs only the application and binds its port to localhost. It does not start or manage PostgreSQL. For cloud mode, add the same read-only Google credential mount to your container configuration.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Container exits before startup | `DATABASE_URL` and the exact allowed origins are required. Check the container log for configuration or migration errors. |
| Health check fails | PostgreSQL must be reachable from the VPS, with valid credentials, TLS settings and database permissions. |
| Reverse proxy reports an unavailable server | Exposed port is `8000`; `/ready` must return 200. Allow the startup period for migrations. |
| A button returns “Origin rejected” | Match `SIGNAL_SLATE_ALLOWED_ORIGINS` to the browser's HTTPS origin, without a trailing slash. |
| Session disappears on local HTTP | Set secure cookies to `false` for local HTTP only. Keep them enabled on the public HTTPS deployment. |
| Gemini shows as unconfigured | The configured Google credential file must exist inside the container and be readable by UID 10001. |
| Cloud check cannot read or publish evidence | Check the Grafana read/write tokens, endpoint URLs and tenant/data-source IDs. |
| Daily limit reached | Live sessions are limited across all visitors. The daily allowance resets at midnight UTC. |

## License

Apache-2.0; see `LICENSE`. The bundled dialogue is synthetic; audio details are in `assets/audio/provenance.json`.
