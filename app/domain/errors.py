class DomainError(Exception):
    pass


class InvalidStateTransitionError(DomainError):
    pass


class CampaignPublicationForbiddenError(DomainError):
    pass


class CampaignNotFoundError(DomainError):
    pass


class WeeklyCommunicationPackNotFoundError(DomainError):
    pass


class WeeklyCommunicationPackConflictError(DomainError):
    pass


class EditorialSourcePackNotFoundError(DomainError):
    pass


class EditorialSourceItemNotFoundError(DomainError):
    pass


class ApprovalPrerequisiteError(DomainError):
    pass


class WebhookSignatureInvalidError(DomainError):
    pass


class UnauthorizedRepositoryError(DomainError):
    pass


class IncompatibleContractVersionError(DomainError):
    pass


class EditorialGenerationBlockedError(DomainError):
    pass


class EmergencyStopActiveError(DomainError):
    pass


class DuplicateCampaignPublicationError(DomainError):
    pass


class ExternalConnectorError(DomainError):
    pass


class OptimisticLockError(DomainError):
    pass


class RateLimitExceededError(ExternalConnectorError):
    pass


class AuthenticationRequiredError(ExternalConnectorError):
    pass


class AuthenticationInvalidError(ExternalConnectorError):
    pass


class RemoteNotFoundError(ExternalConnectorError):
    pass


class RemoteConflictError(ExternalConnectorError):
    pass


class RemoteValidationError(ExternalConnectorError):
    pass


class RemoteUnsupportedError(ExternalConnectorError):
    pass


class RemoteContractError(ExternalConnectorError):
    pass


class RemoteTimeoutError(ExternalConnectorError):
    pass
