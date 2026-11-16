"""kyc-desk: an Indian KYC onboarding desk for training and testing AI agents."""

__version__ = "0.1.0"

from .env import Env, tool_schemas  # noqa: E402
from .policies import POLICIES, ReferenceAgent, run_policy  # noqa: E402
from .world import LEVELS, generate  # noqa: E402

__all__ = ["Env", "tool_schemas", "POLICIES", "ReferenceAgent", "run_policy", "LEVELS", "generate"]
