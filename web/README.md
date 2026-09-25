# Link Vault dashboard

Next.js (App Router) dashboard for the Link Vault API. See the root `README.md` for the
whole project; this is the `web` service.

```bash
nvm use            # Node 24 LTS, from .nvmrc (the Docker image and CI use the same)
npm install
# API_KEY must match the API's; API_BASE_URL defaults to http://localhost:8000.
printf 'API_KEY=change-me\nAPI_BASE_URL=http://localhost:8000\n' > .env.local
npm run dev        # http://localhost:3000

npm run lint && npm run typecheck && npm test
```

- `src/lib/api.ts` is the only module that calls the API. It's `server-only`, so the API key
  never reaches the browser; client components go through the server actions in
  `src/app/actions.ts`.
- Filters live in the URL (`/?type=tweet&tag=ai&page=2`); `src/lib/filters.ts` converts them
  to the API's query.
- Cached thumbnails are proxied by `src/app/thumbnails/[file]/route.ts`, which adds the key.
