"""
The user's .env: settings for runs on their own machine, never in CI.
"""

import os

from dotenv import find_dotenv, load_dotenv

NOT_SET = ("", "0", "false")


def in_ci() -> bool:
    # GitHub Actions and GitLab CI both set CI=true
    return os.getenv("CI", "").strip().lower() not in NOT_SET


def load_user_env() -> None:
    """
    Load the .env of the current directory (the analyzed repository), not one
    searched upward from the installed package.

    Skipped in CI: there the working tree is the change under review, and a
    .env committed in it could point ANTHROPIC_BASE_URL (which the SDK honours)
    at another host and walk off with the key. CI settings come from CI
    variables.
    """
    if in_ci():
        return
    load_dotenv(find_dotenv(usecwd=True))
