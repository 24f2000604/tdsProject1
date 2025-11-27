# TDS Project

Basic Flask API with CORS enabled.

## Running the app

```bash
# (optional) create & activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# install dependencies defined in pyproject.toml
pip install -U pip setuptools wheel
pip install -e .

# run the dev server
python app.py
```

The API will be available at `http://127.0.0.1:5000`. Try:

- `GET /api/hello` – returns a JSON greeting (CORS-enabled for `/api/*`).
- `GET /health` – simple health-check endpoint.
- `POST /api/quiz_solver` – accepts `{ "secret": "..." }` JSON and reports whether it
  matches the server-side secret (`USER_SECRET`).

## Environment variables

Copy `.env.example` to `.env` (or export manually) and fill in your own values:

- `USER_EMAIL` – the email address you registered in the Google Form.
- `USER_SECRET` – the secret token that must match incoming payloads.
- `OPENAI_API_KEY` – used by the autonomous agent to call the Assistants API.
- `AIPipe_TOKEN`, `SCRAPPER_API_TOKEN` – optional tokens if you route calls through
  AI Pipe or other scraping infrastructure.

## Quiz solver endpoint

`POST /api/quiz_solver`

```json
{
  "email": "student@example.com",
  "secret": "my-shared-secret",
  "url": "https://example.com/quiz-834",
  "notes": "(optional) any extra metadata you want the agent to see"
}
```

Rules enforced by the API:

1. Requests must contain valid JSON; otherwise it returns **400**.
2. Secrets must match `USER_SECRET`; otherwise it returns **403**.
3. On success, the server builds a detailed agent prompt, calls the autonomous solver,
   and responds with **200** containing the run/thread identifiers plus the assistant's
   latest answer.
