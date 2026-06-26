"""ADS Decomposer runtime package."""

from .handoff import (
    DECOMPOSER_HANDOFF_SCHEMA_VERSION,
    DECOMPOSER_MODEL_LANE_ID,
    DECOMPOSER_MODEL_ID,
    DecomposerHandoffError,
    build_decomposer_handoff,
    resolve_decomposer_model_lane,
    validate_decomposer_handoff,
)
from .qdt import (
    ANCHOR_DEPENDENCY_CONTRACT_SCHEMA_VERSION,
    QUESTION_DECOMPOSITION_ARTIFACT_TYPE,
    QDTError,
    build_anchor_dependency_contract,
    build_fixture_qdt_candidate,
    build_leaf_budget_decision,
    build_qdt_candidate,
    build_research_sufficiency_requirements,
    repair_anchor_dependency_contracts,
    select_qdt_candidate,
    validate_anchor_dependency_contract,
    validate_qdt_structure,
    validate_question_decomposition,
    validate_question_decomposition_against_amrg_context,
)
from .persistence import (
    QDTPersistenceError,
    ensure_qdt_persistence_schema,
    write_decomposition_run,
    write_qdt_research_sufficiency_requirements,
)
from .sufficiency_requirements import (
    RESEARCH_SUFFICIENCY_REQUIREMENTS_SCHEMA_VERSION,
    RESEARCH_SUFFICIENCY_TEMPLATE_VERSION,
)

__all__ = [
    "DECOMPOSER_HANDOFF_SCHEMA_VERSION",
    "DECOMPOSER_MODEL_LANE_ID",
    "DECOMPOSER_MODEL_ID",
    "DecomposerHandoffError",
    "ANCHOR_DEPENDENCY_CONTRACT_SCHEMA_VERSION",
    "QDTPersistenceError",
    "QDTError",
    "QUESTION_DECOMPOSITION_ARTIFACT_TYPE",
    "RESEARCH_SUFFICIENCY_REQUIREMENTS_SCHEMA_VERSION",
    "RESEARCH_SUFFICIENCY_TEMPLATE_VERSION",
    "build_anchor_dependency_contract",
    "build_decomposer_handoff",
    "build_fixture_qdt_candidate",
    "build_leaf_budget_decision",
    "build_qdt_candidate",
    "build_research_sufficiency_requirements",
    "ensure_qdt_persistence_schema",
    "repair_anchor_dependency_contracts",
    "resolve_decomposer_model_lane",
    "select_qdt_candidate",
    "validate_anchor_dependency_contract",
    "validate_decomposer_handoff",
    "validate_qdt_structure",
    "validate_question_decomposition",
    "validate_question_decomposition_against_amrg_context",
    "write_decomposition_run",
    "write_qdt_research_sufficiency_requirements",
]
