import ast
from pathlib import Path

from src.core.policy_packs.ai_models import (
    PolicyEvaluationAiEvidenceRequest as AiPolicyEvaluationAiEvidenceRequest,
)
from src.core.policy_packs.ai_models import (
    PolicyEvaluationAiEvidenceResponse as AiPolicyEvaluationAiEvidenceResponse,
)
from src.core.policy_packs.catalog_models import (
    PolicyPackActivationRequest as CatalogPolicyPackActivationRequest,
)
from src.core.policy_packs.catalog_models import (
    PolicyPackActivationResponse as CatalogPolicyPackActivationResponse,
)
from src.core.policy_packs.catalog_models import (
    PolicyPackAuditEvent as CatalogPolicyPackAuditEvent,
)
from src.core.policy_packs.catalog_models import (
    PolicyPackDetailResponse as CatalogPolicyPackDetailResponse,
)
from src.core.policy_packs.catalog_models import (
    PolicyPackListResponse as CatalogPolicyPackListResponse,
)
from src.core.policy_packs.catalog_models import (
    PolicyPackSummary as CatalogPolicyPackSummary,
)
from src.core.policy_packs.catalog_models import (
    PolicyPackValidationRequest as CatalogPolicyPackValidationRequest,
)
from src.core.policy_packs.catalog_models import (
    PolicyPackValidationResponse as CatalogPolicyPackValidationResponse,
)
from src.core.policy_packs.evaluation_models import (
    PolicyPackApplicabilityResult as EvaluationPolicyPackApplicabilityResult,
)
from src.core.policy_packs.evaluation_models import (
    PolicyPackEvaluationResponse as EvaluationPolicyPackEvaluationResponse,
)
from src.core.policy_packs.evaluation_models import (
    PolicyRuleEvaluationResult as EvaluationPolicyRuleEvaluationResult,
)
from src.core.policy_packs.models import (
    PolicyEvaluationAiEvidenceRequest,
    PolicyEvaluationAiEvidenceResponse,
    PolicyEvaluationAuditEvent,
    PolicyEvaluationCreateRequest,
    PolicyEvaluationEventRequest,
    PolicyEvaluationLineageResponse,
    PolicyEvaluationPersistenceResult,
    PolicyEvaluationRecord,
    PolicyEvaluationReplayRequest,
    PolicyEvaluationReplayResponse,
    PolicyEvaluationReportPackageRequest,
    PolicyEvaluationReportPackageResponse,
    PolicyEvaluationRequirementProjection,
    PolicyEvaluationReviewQueueResponse,
    PolicyEvaluationSignOffDecisionRequest,
    PolicyEvaluationSignOffDecisionResponse,
    PolicyEvaluationSignOffPackageResponse,
    PolicyEvaluationWorkflowMetadata,
    PolicyEvaluationWorkflowReplayMetadata,
    PolicyEvaluationWorkflowResponse,
    PolicyPackActivationRequest,
    PolicyPackActivationResponse,
    PolicyPackApplicabilityResult,
    PolicyPackAuditEvent,
    PolicyPackDetailResponse,
    PolicyPackEvaluationResponse,
    PolicyPackListResponse,
    PolicyPackSummary,
    PolicyPackValidationRequest,
    PolicyPackValidationResponse,
    PolicyRuleEvaluationResult,
)
from src.core.policy_packs.persistence_models import (
    PolicyEvaluationAuditEvent as PersistencePolicyEvaluationAuditEvent,
)
from src.core.policy_packs.persistence_models import (
    PolicyEvaluationCreateRequest as PersistencePolicyEvaluationCreateRequest,
)
from src.core.policy_packs.persistence_models import (
    PolicyEvaluationEventRequest as PersistencePolicyEvaluationEventRequest,
)
from src.core.policy_packs.persistence_models import (
    PolicyEvaluationPersistenceResult as PersistencePolicyEvaluationPersistenceResult,
)
from src.core.policy_packs.persistence_models import (
    PolicyEvaluationRecord as PersistencePolicyEvaluationRecord,
)
from src.core.policy_packs.persistence_models import (
    PolicyEvaluationReplayRequest as PersistencePolicyEvaluationReplayRequest,
)
from src.core.policy_packs.persistence_models import (
    PolicyEvaluationReplayResponse as PersistencePolicyEvaluationReplayResponse,
)
from src.core.policy_packs.projection_models import (
    PolicyEvaluationLineageResponse as ProjectionPolicyEvaluationLineageResponse,
)
from src.core.policy_packs.projection_models import (
    PolicyEvaluationReviewQueueResponse as ProjectionPolicyEvaluationReviewQueueResponse,
)
from src.core.policy_packs.projection_models import (
    PolicyEvaluationSignOffPackageResponse as ProjectionPolicyEvaluationSignOffPackageResponse,
)
from src.core.policy_packs.reporting_models import (
    PolicyEvaluationReportPackageRequest as ReportingPolicyEvaluationReportPackageRequest,
)
from src.core.policy_packs.reporting_models import (
    PolicyEvaluationReportPackageResponse as ReportingPolicyEvaluationReportPackageResponse,
)
from src.core.policy_packs.workflow_models import (
    PolicyEvaluationRequirementProjection as WorkflowPolicyEvaluationRequirementProjection,
)
from src.core.policy_packs.workflow_models import (
    PolicyEvaluationSignOffDecisionRequest as WorkflowPolicyEvaluationSignOffDecisionRequest,
)
from src.core.policy_packs.workflow_models import (
    PolicyEvaluationSignOffDecisionResponse as WorkflowPolicyEvaluationSignOffDecisionResponse,
)
from src.core.policy_packs.workflow_models import (
    PolicyEvaluationWorkflowMetadata as WorkflowPolicyEvaluationWorkflowMetadata,
)
from src.core.policy_packs.workflow_models import (
    PolicyEvaluationWorkflowReplayMetadata as WorkflowPolicyEvaluationWorkflowReplayMetadata,
)
from src.core.policy_packs.workflow_models import (
    PolicyEvaluationWorkflowResponse as WorkflowPolicyEvaluationWorkflowResponse,
)

MODELS_SOURCE_PATH = Path("src/core/policy_packs/models.py")
SRC_ROOT = Path("src")


def test_policy_pack_models_preserves_catalog_model_import_contract():
    assert PolicyPackActivationRequest is CatalogPolicyPackActivationRequest
    assert PolicyPackActivationResponse is CatalogPolicyPackActivationResponse
    assert PolicyPackAuditEvent is CatalogPolicyPackAuditEvent
    assert PolicyPackDetailResponse is CatalogPolicyPackDetailResponse
    assert PolicyPackListResponse is CatalogPolicyPackListResponse
    assert PolicyPackSummary is CatalogPolicyPackSummary
    assert PolicyPackValidationRequest is CatalogPolicyPackValidationRequest
    assert PolicyPackValidationResponse is CatalogPolicyPackValidationResponse


def test_policy_pack_models_preserves_evaluation_model_import_contract():
    assert PolicyPackApplicabilityResult is EvaluationPolicyPackApplicabilityResult
    assert PolicyPackEvaluationResponse is EvaluationPolicyPackEvaluationResponse
    assert PolicyRuleEvaluationResult is EvaluationPolicyRuleEvaluationResult


def test_policy_pack_models_preserves_persistence_model_import_contract():
    assert PolicyEvaluationAuditEvent is PersistencePolicyEvaluationAuditEvent
    assert PolicyEvaluationCreateRequest is PersistencePolicyEvaluationCreateRequest
    assert PolicyEvaluationEventRequest is PersistencePolicyEvaluationEventRequest
    assert PolicyEvaluationPersistenceResult is PersistencePolicyEvaluationPersistenceResult
    assert PolicyEvaluationRecord is PersistencePolicyEvaluationRecord
    assert PolicyEvaluationReplayRequest is PersistencePolicyEvaluationReplayRequest
    assert PolicyEvaluationReplayResponse is PersistencePolicyEvaluationReplayResponse


def test_policy_pack_models_preserves_workflow_model_import_contract():
    assert PolicyEvaluationRequirementProjection is WorkflowPolicyEvaluationRequirementProjection
    assert PolicyEvaluationSignOffDecisionRequest is WorkflowPolicyEvaluationSignOffDecisionRequest
    assert (
        PolicyEvaluationSignOffDecisionResponse is WorkflowPolicyEvaluationSignOffDecisionResponse
    )
    assert PolicyEvaluationWorkflowResponse is WorkflowPolicyEvaluationWorkflowResponse
    assert PolicyEvaluationWorkflowMetadata is WorkflowPolicyEvaluationWorkflowMetadata
    assert PolicyEvaluationWorkflowReplayMetadata is WorkflowPolicyEvaluationWorkflowReplayMetadata


def test_policy_pack_models_preserves_reporting_model_import_contract():
    assert PolicyEvaluationReportPackageRequest is ReportingPolicyEvaluationReportPackageRequest
    assert PolicyEvaluationReportPackageResponse is ReportingPolicyEvaluationReportPackageResponse


def test_policy_pack_models_preserves_ai_model_import_contract():
    assert PolicyEvaluationAiEvidenceRequest is AiPolicyEvaluationAiEvidenceRequest
    assert PolicyEvaluationAiEvidenceResponse is AiPolicyEvaluationAiEvidenceResponse


def test_policy_pack_models_preserves_projection_model_import_contract():
    assert PolicyEvaluationLineageResponse is ProjectionPolicyEvaluationLineageResponse
    assert PolicyEvaluationReviewQueueResponse is ProjectionPolicyEvaluationReviewQueueResponse
    assert (
        PolicyEvaluationSignOffPackageResponse is ProjectionPolicyEvaluationSignOffPackageResponse
    )


def test_policy_pack_models_is_pure_compatibility_facade():
    tree = ast.parse(MODELS_SOURCE_PATH.read_text(encoding="utf-8"))

    assert not [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
    assert not [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]


def test_production_code_uses_focused_policy_pack_model_imports():
    compatibility_importers = sorted(
        path.as_posix()
        for path in SRC_ROOT.rglob("*.py")
        if path.as_posix() != "src/core/policy_packs/models.py"
        and "src.core.policy_packs.models" in path.read_text(encoding="utf-8")
    )

    assert compatibility_importers == []
