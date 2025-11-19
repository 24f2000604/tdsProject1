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
