"""Stable domain errors raised by the public App Evolver API."""


class AppEvolverError(ValueError):
    """Base class for expected App Evolver failures."""


class ConfigurationError(AppEvolverError):
    """The app contract, constitution, or agent configuration is invalid."""


class NotFoundError(AppEvolverError):
    """A requested app, observation, agent, or pull request does not exist."""


class PolicyViolation(AppEvolverError):
    """A requested operation is outside the configured evolution authority."""


class InvalidTransition(AppEvolverError):
    """A workflow object cannot move from its current state as requested."""


class ValidationFailed(AppEvolverError):
    """A proposed change did not pass the companion repository's checks."""


class DeliveryError(AppEvolverError):
    """A checked branch could not be delivered through the Git provider."""


class AgentExecutionError(AppEvolverError):
    """One member of a composite agent wave failed."""

    def __init__(self, agent_id: str, cause: Exception):
        self.agent_id = agent_id
        self.cause = cause
        super().__init__(f"Agent {agent_id} failed: {cause}")
