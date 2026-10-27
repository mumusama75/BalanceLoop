"""Enumerations of the BalanceLoop domain.

Every ``«enumeration»`` of the Stage 1 class diagram (Fig. 3) is reproduced here,
plus the state sets of the state machines (Fig. 7, 10, 13, 16, 21, 22, 25) that
are persisted as ``status`` columns.
"""
from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover
        return str(self.value)


# ---- Agents -----------------------------------------------------------------
class AgentRole(StrEnum):
    ORCHESTRATOR = "Orchestrator"
    NUTRITION_COACH = "NutritionCoach"
    FITNESS_COACH = "FitnessCoach"
    SAFETY_SUPERVISOR = "SafetySupervisor"


# ---- UC01 Profile & consent -------------------------------------------------
class ProfileStatus(StrEnum):
    EDITING = "Editing"
    INTERPRETING = "Interpreting"
    AWAITING_FORM_INPUT = "AwaitingFormInput"
    AWAITING_CONFIRMATION = "AwaitingConfirmation"
    AWAITING_CONSENT = "AwaitingConsent"
    VALIDATING = "Validating"
    SAVING = "Saving"
    ACTIVE = "Active"
    INCOMPLETE = "Incomplete"
    CONSENT_WITHDRAWN = "ConsentWithdrawn"
    DISCARDED = "Discarded"


class ConsentScope(StrEnum):
    CORE = "core"          # required processing consent
    O1 = "O1"              # optional: adaptive calorie disclosure
    O2 = "O2"              # optional: wearable data import


class AllergyStatus(StrEnum):
    NONE = "none"          # user confirmed: no allergies
    KNOWN = "known"        # user listed allergies
    UNKNOWN = "unknown"    # unanswered -> never treated as "no allergies"


# ---- UC02 Food entry --------------------------------------------------------
class FoodEntryStatus(StrEnum):
    # transient (class diagram)
    RECEIVED = "Received"
    IDENTIFYING = "Identifying"
    AWAITING_CHOICE = "AwaitingChoice"
    ESTIMATING = "Estimating"
    SAVING = "Saving"
    ANALYSED = "Analysed"
    QUEUED_FOR_REVIEW = "QueuedForReview"
    UNANALYSED = "Unanalysed"
    DISCARDED = "Discarded"
    # persisted (state machine Fig. 7)
    DRAFT = "Draft"
    AWAITING_CLARIFICATION = "AwaitingClarification"
    RECORDED_UNESTIMATED = "RecordedUnestimated"
    PENDING_REVIEW = "PendingReview"
    REVISION_REQUIRED = "RevisionRequired"
    RELEASED = "Released"
    WITHHELD = "Withheld"


# ---- UC03/04 Diet -----------------------------------------------------------
class FeedbackStatus(StrEnum):
    RECEIVED = "Received"
    ANALYSING = "Analysing"
    AWAITING_CLARIFICATION = "AwaitingClarification"
    CHECKING_STRATEGY = "CheckingStrategy"
    PROPOSING = "Proposing"
    SAVING_REVISION = "SavingRevision"
    SUBMITTING = "Submitting"
    PENDING_REVIEW = "PendingReview"
    APPLIED = "Applied"
    NOT_APPLIED = "NotApplied"
    ABANDONED = "Abandoned"


class DietAdaptationStrategy(StrEnum):
    MINIMAL_CHANGE = "MinimalChange"
    SAFE_ALTERNATIVE = "SafeAlternative"


# ---- UC05 Readiness ---------------------------------------------------------
class ReadinessResult(StrEnum):
    READY = "Ready"
    REDUCED = "Reduced"
    RECOVERY = "Recovery"


class AssessmentStatus(StrEnum):
    AWAITING_INPUT = "AwaitingInput"
    VALIDATING = "Validating"
    AWAITING_CLARIFICATION = "AwaitingClarification"
    ASSESSING = "Assessing"
    SAVING = "Saving"
    COMPLETED = "Completed"
    INCOMPLETE = "Incomplete"


# ---- UC06 Exercise planning request ----------------------------------------
class RequestState(StrEnum):
    DRAFTING = "Drafting"
    SUBMITTING = "Submitting"
    PENDING_REVIEW = "PendingReview"
    REVISION_REQUIRED = "RevisionRequired"
    RELEASED = "Released"
    WITHHELD = "Withheld"
    ABANDONED = "Abandoned"


class Intensity(StrEnum):
    LIGHT = "light"
    LIGHT_MODERATE = "light-moderate"
    MODERATE = "moderate"
    VIGOROUS = "vigorous"


INTENSITY_RANK = {Intensity.LIGHT: 0, Intensity.LIGHT_MODERATE: 1, Intensity.MODERATE: 2, Intensity.VIGOROUS: 3}


# ---- UC07/08 Activity feedback & adaptation --------------------------------
class CompletionStatus(StrEnum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    SKIPPED = "skipped"


class FeedbackRecordStatus(StrEnum):
    LOADING_PLAN = "LoadingPlan"
    VALIDATING = "Validating"
    AWAITING_CLARIFICATION = "AwaitingClarification"
    INTERPRETING = "Interpreting"
    CHECKING_RULES = "CheckingRules"
    SAVING = "Saving"
    RECORDED = "Recorded"
    FLAGGED = "Flagged"
    INCOMPLETE = "Incomplete"


class AdaptationAction(StrEnum):
    MAINTAIN = "Maintain"
    REDUCE = "Reduce"
    REPLACE = "Replace"
    PAUSE = "Pause"


class AdaptationStatus(StrEnum):
    PROPOSING = "Proposing"
    CHECKING_LOAD = "CheckingLoad"
    SAVING = "Saving"
    SUBMITTING = "Submitting"
    PENDING_REVIEW = "PendingReview"
    APPLIED = "Applied"
    DISCARDED = "Discarded"


# ---- UC09 Integration -------------------------------------------------------
class IntegrationState(StrEnum):
    AWAITING_CANDIDATES = "AwaitingCandidates"
    RECONCILING = "Reconciling"
    AWAITING_CORRECTION = "AwaitingCorrection"
    SAVING = "Saving"
    SUBMITTING = "Submitting"
    PENDING_REVIEW = "PendingReview"
    RELEASED = "Released"
    WITHHELD = "Withheld"
    ABANDONED = "Abandoned"


class ConflictType(StrEnum):
    TIMING = "timing"
    RECOVERY = "recovery"
    WORKLOAD = "workload"
    NUTRITION = "nutrition"
    PROFILE_VERSION = "profile_version"


# ---- UC10 Review ------------------------------------------------------------
class CandidateKind(StrEnum):
    DIET = "diet"
    EXERCISE = "exercise"
    INTEGRATED = "integrated"
    FOOD_ANALYSIS = "food_analysis"


class CandidateStatus(StrEnum):
    """Generic lifecycle shared by all PlanCandidate kinds."""
    DRAFT = "Draft"
    PENDING_REVIEW = "PendingReview"
    REVISION_REQUIRED = "RevisionRequired"
    RELEASED = "Released"
    WITHHELD = "Withheld"
    SUPERSEDED = "Superseded"
    PLACEHOLDER = "Placeholder"


class ReviewCaseState(StrEnum):
    PENDING_VALIDATION = "PendingValidation"
    UNDER_REVIEW = "UnderReview"
    APPROVED = "Approved"
    AWAITING_REVISION = "AwaitingRevision"
    CHECKING_SAFE_FALLBACK = "CheckingSafeFallback"
    RELEASED = "Released"
    WITHHELD = "Withheld"


class DecisionType(StrEnum):
    APPROVE = "Approve"
    REVISE_AND_REVIEW = "ReviseAndReview"
    SAFE_FALLBACK = "SafeFallback"
    WITHHOLD = "Withhold"
    CRITICAL_STOP = "CriticalStop"


class RiskLevel(StrEnum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class OutcomeStatus(StrEnum):
    """Status returned to the user by every personalised operation."""
    RELEASED = "released"
    SAFE_RESPONSE = "safe_response"
    SUPPORT_NOTICE = "support_notice"
    WITHHELD = "withheld"
    CLARIFICATION = "clarification"
    RECORDED_UNESTIMATED = "recorded_unestimated"
    NOT_INTEGRATED = "not_integrated"
    PENDING_READINESS = "pending_readiness"
    BLOCKED = "blocked"           # consent / profile preconditions not met
    INFO = "info"


class NotificationKind(StrEnum):
    RELEASE = "release"
    SAFE_RESPONSE = "safe_response"
    SUPPORT_NOTICE = "support_notice"
    CLARIFICATION = "clarification"
    INFO = "info"
    INCIDENT = "incident"  # founder-facing
