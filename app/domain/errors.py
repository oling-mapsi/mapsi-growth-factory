class DomainError(Exception):
    pass


class InvalidStateTransitionError(DomainError):
    pass


class CampaignPublicationForbiddenError(DomainError):
    pass


class CampaignNotFoundError(DomainError):
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


class RateLimitExceededError(ExternalConnectorError):
    pass
