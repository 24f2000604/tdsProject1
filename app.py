"""Basic Flask app with CORS enabled."""

from datetime import datetime
import os

import dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

from aiTest import solve_quiz_question

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
		"""Validate the submitted secret against the configured one."""

		payload = request.get_json(silent=True) or {}
		submitted_secret = payload.get("secret")
		result = solve_quiz_question(submitted_secret, USER_SECRET)

		status_code = 200 if result.correct else 400
		return (
			jsonify(
				{
					"app": app.config["APP_NAME"],
					"email": USER_EMAIL,
					"correct": result.correct,
					"message": result.message,
				}
			),
			status_code,
		)

	return app


app = create_app()


if __name__ == "__main__":
	# Use Flask's built-in development server
	app.run(host="0.0.0.0", port=5000, debug=True)

