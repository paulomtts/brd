class BrdError(Exception):
    """Base for every domain error; the CLI turns these into error envelopes."""


class ProjectNotFoundError(BrdError):
    pass


class ProjectAlreadyExistsError(BrdError):
    pass


class MigrationError(BrdError):
    pass


class CycleError(BrdError):
    pass


class InvalidStatusError(BrdError):
    pass


class CardAlreadyExistsError(BrdError):
    pass


class EntityAlreadyExistsError(BrdError):
    pass


class CardHasChildrenError(BrdError):
    pass


class EntityNotFoundError(BrdError):
    pass


class CardNotFoundError(EntityNotFoundError):
    pass


class IssueNotFoundError(EntityNotFoundError):
    pass


class DocumentNotFoundError(EntityNotFoundError):
    pass


class CommentNotFoundError(BrdError):
    pass


class EmptyCommentError(BrdError):
    pass


class DuplicateStemError(BrdError):
    pass


class DuplicatePathError(BrdError):
    pass


class PathOutsideProjectError(BrdError):
    pass


class NotMarkdownError(BrdError):
    pass


class DocumentSourceNotFoundError(BrdError):
    pass


class DocumentContentLostError(BrdError):
    pass


class RestoreConflictError(BrdError):
    pass


class NotTaggableError(BrdError):
    pass


class NotCommentableError(BrdError):
    pass


class InvalidBlockerError(BrdError):
    pass


class InvalidTagError(BrdError):
    pass


class InvalidCloseReasonError(BrdError):
    pass


class SelfReferenceError(BrdError):
    pass


class ImportFormatError(BrdError):
    pass


class ImportReadError(BrdError):
    pass


class ProjectNotEmptyError(BrdError):
    pass


class ProjectRootNotFoundError(BrdError):
    pass
