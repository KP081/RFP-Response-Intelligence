# Frontend implementation notes

- `VITE_API_BASE_URL` is expected to include the backend's `/api/v1` prefix. When it is unset, the API
  client uses same-origin paths, which supports a local development proxy or a reverse proxy deployment.
- The Dockerfile is designed to be built with `frontend/` as its build context: `docker build -t frontend .`.
