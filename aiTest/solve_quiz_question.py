"""Utility helpers for solving quiz secrets."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuizResult:
    """Represents the outcome of checking a quiz secret."""

    correct: bool
    message: str


def solve_quiz_question(submitted_secret: str | None, actual_secret: str | None) -> QuizResult:
    """Compare the submitted secret with the expected secret.

    Args:
        submitted_secret: The secret provided by the caller (may be missing/None).
        actual_secret: The expected secret stored on the server (may be missing/None).

    Returns:
        QuizResult describing whether the check passed and a human-readable reason.
    """

    if not actual_secret:
        return QuizResult(
            correct=False,
            message="Server secret is not configured. Please set USER_SECRET.",
        )

    if not submitted_secret:
        return QuizResult(correct=False, message="Please provide a secret value.")

    if submitted_secret.strip() == actual_secret:
        return QuizResult(correct=True, message="Secret accepted. Great job!")

    return QuizResult(correct=False, message="Secret mismatch. Try again.")
