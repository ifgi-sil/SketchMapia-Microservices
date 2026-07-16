# Adding a New Microservice

Checklist for adding a service to SketchMapia. Six places must be updated —
missing any one of them causes a different failure, listed at each step.
The examples use a fictional service `myservice` on port `8007` (ports
8000–8006 are taken; each service gets the next free one).

Overview of the moving parts:

| # | File | Purpose | Symptom if forgotten |
|---|------|---------|----------------------|
| 1 | `<service>/` directory | The Django service itself | — |
| 2 | `docker-compose.yml` | Local development (builds from source) | Service missing locally |
| 3 | `.github/workflows/registry-build-publish.yml` | Publishes image to GHCR on push to `main` | `manifest unknown` when the server pulls |
| 4 | `sketchmap_analyser/static/js/project.js` | Frontend port map + API calls | Frontend can't reach service in local dev |
| 5 | `docker-compose.server.yml` | Production compose (pulls GHCR images) | Service never starts on server |
| 6 | `docs/apache-sketchmapia-ssl.conf` | Reverse proxy on the server | 404s in production (browser hits Apache, not ports) |

## 1. Create the service

Copy the structure of an existing service (e.g. `gmda/`):

```
myservice/
├── Dockerfile              # same pattern as gmda/Dockerfile, EXPOSE 8007
├── requirements.txt
├── manage.py
├── myservice/              # Django project
│   ├── settings.py         # CORS config like the other services
│   └── urls.py             # path('myservice/', include('microservice.urls'))
└── microservice/           # Django app with the actual endpoints
```

Conventions that matter:

- **Mount all routes under the service's own prefix** (`path('myservice/', ...)`
  in the project `urls.py`). The Apache proxy and the frontend both rely on it.
- **Commit your migration files** and use `migrate` only (not `makemigrations`)
  in the Dockerfile CMD and compose command — generate migrations at development
  time, never at container start.
- Do not commit `db.sqlite3` or `__pycache__/` (covered by `.gitignore`).

## 2. Local development compose — `docker-compose.yml`

```yaml
  myservice:
    build: ./myservice
    command: bash -c "python manage.py migrate && python manage.py runserver 0.0.0.0:8007"
    ports:
      - "8007:8007"
    volumes:
      - ./myservice:/app
    restart: always
```

Test locally: `docker-compose up --build`, then hit `http://localhost:8007/myservice/...`.

## 3. CI workflow — `.github/workflows/registry-build-publish.yml`

Add a build/push step mirroring the existing ones:

```yaml
      - name: Build and Push myservice
        uses: docker/build-push-action@v5
        with:
          context: ./myservice
          file: ./myservice/Dockerfile
          platforms: linux/amd64
          push: true
          tags: ghcr.io/${{ env.owner_lc }}/myservice:latest
```

The workflow only runs on pushes to `main` — the image does not exist until
the change is merged.

## 4. Frontend — `sketchmap_analyser/static/js/project.js`

Add the service to the port map inside `getServiceUrl()`:

```js
        const portMap = {
            ...
            myservice: 8007
        };
```

In local dev the frontend calls `http://localhost:8007/...` directly; in
production it calls same-origin paths (`https://<host>/myservice/...`) that
Apache proxies. Write API calls as `${getServiceUrl('myservice')}/myservice/<endpoint>/`.

## 5. Server compose — `docker-compose.server.yml`

```yaml
  myservice:
    image: ghcr.io/ifgi-sil/myservice:latest
    platform: linux/amd64
    ports:
      - "8007:8007"
    restart: always
```

## 6. Apache reverse proxy — `docs/apache-sketchmapia-ssl.conf`

Add the block **before** the catch-all `ProxyPass /` (Apache uses the first
matching rule):

```apache
    # Myservice
    ProxyPassMatch ^/myservice/(.*)$ http://localhost:8007/myservice/$1
    ProxyPassReverse /myservice/ http://localhost:8007/myservice/
```

Do **not** open port 8007 in the server firewall — all production traffic
goes through Apache on 443; the service ports are localhost-only.

## Deploying

1. **Merge to `main`.** The GitHub Action builds and pushes the image — check
   the Actions tab for a green "Build and Push Docker Images" run.
2. **First publish only:** GHCR creates new packages as *private*. Make the
   package public (GitHub → org → Packages → package settings → visibility),
   matching the other services. A private package fails on the server with
   `denied`; a missing one with `manifest unknown`.
3. **Update the server compose file** (deployment directory on the server)
   with the block from step 5, then:

   ```bash
   sudo docker compose pull
   sudo docker compose up -d
   ```

   Watchtower keeps *running* containers updated automatically (polls GHCR
   every 60 s), but it never creates containers for newly added services —
   the initial `up -d` is always manual.
4. **Update the Apache vhost** on the server:

   ```bash
   cd /etc/apache2/sites-available
   sudo vim sketchmapia-ssl.conf        # paste the block from step 6
   sudo apachectl configtest            # must report "Syntax OK"
   sudo systemctl reload apache2
   ```

5. **Verify from outside the server:**

   ```bash
   curl -I https://sketchmapia.uni-muenster.de/myservice/<some-endpoint>/
   ```

   A `404` from Apache (not Django) usually means the proxy block is missing
   or placed after the catch-all; a `502` means the container isn't running
   or the port doesn't match.
