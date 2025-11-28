"""Basic Flask app with CORS enabled."""

from __future__ import annotations

from datetime import datetime
import json
import os
from typing import Any, Dict

import dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.exceptions import BadRequest

from aiTest import solve_quiz_question
from asgiref.wsgi import WsgiToAsgi

dotenv.load_dotenv()

USER_EMAIL = os.environ.get("USER_EMAIL", "default_email")
USER_SECRET = os.environ.get("USER_SECRET", "yoursecret")

def create_app(config: dict | None = None) -> Flask:
	"""Application factory so the app can be imported for tests."""

	app = Flask(__name__)
	default_config = {
		"APP_NAME": "TDS Project API",
		"CORS_RESOURCES": {r"/api/*": {"origins": "*"}},
	}
	app.config.update(default_config)
	if config:
		app.config.update(config)

	CORS(app, resources=app.config["CORS_RESOURCES"])

	@app.get("/api/hello")
	def hello_world():
		"""Simple endpoint to verify the stack works."""

		return jsonify(
			{
				"app": app.config["APP_NAME"],
				"message": "Hello from Flask with CORS!",
				"timestamp": datetime.utcnow().isoformat() + "Z",
				"client": request.remote_addr,
			}
		)

	@app.get("/health")
	def health() -> tuple[dict, int]:
		"""Lightweight health-check endpoint."""

		return {"status": "ok", "app": app.config["APP_NAME"]}, 200

	@app.post("/api/quiz_solver")
	def quiz_solver():
		"""Validate payload, verify secret, and trigger the autonomous quiz solver."""

		# Handle invalid JSON - force=True raises BadRequest on invalid JSON
		try:
			payload = request.get_json(force=True)
		except Exception:
			return jsonify({"error": "Invalid JSON payload."}), 400

		if payload is None or not isinstance(payload, dict):
			return jsonify({"error": "Invalid JSON payload."}), 400

		required_fields = ("email", "secret", "url")
		missing = [field for field in required_fields if not payload.get(field)]
		if missing:
			return (
				jsonify({"error": f"Missing required field(s): {', '.join(missing)}."}),
				400,
			)

		if payload["secret"] != USER_SECRET:
			return jsonify({"error": "Forbidden: secret mismatch."}), 403

		prompt = _build_quiz_prompt(payload)
		solver_response = solve_quiz_question(prompt, verbose=False)

		if solver_response.get("status") != "completed":
			return (
				jsonify(
					{
						"status": solver_response.get("status"),
						"message": solver_response.get("error", "Quiz solver failed."),
						"thread_id": solver_response.get("thread_id"),
						"run_id": solver_response.get("run_id"),
					}
				),
				500,
			)

		return (
			jsonify(
				{
					"status": "ok",
					"thread_id": solver_response.get("thread_id"),
					"run_id": solver_response.get("run_id"),
					"answer": solver_response.get("answer"),
					"attachments": solver_response.get("attachments", []),
					"email": payload["email"],
				}
			),
			200,
		)

	return app


app = create_app()
asgi_app = WsgiToAsgi(app)


if __name__ == "__main__":
	# Use Flask's built-in development server
	app.run(host="0.0.0.0", port=5000, debug=True)


def _build_quiz_prompt(payload: Dict[str, Any]) -> str:
	"""Create a detailed instruction block for the autonomous quiz solver."""

	return (
		f"solve {payload['url']}, "
		f"When posting the JSON, include 'email': '{payload['email']}' and 'secret': '{payload['secret']}' in the payload. "
		f"keep checking any urls provided until you get the final answer. a successful response might contain urls with additional problems"
	)

