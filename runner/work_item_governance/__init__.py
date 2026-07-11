"""Public Work Item Governance API.

The package is deliberately independent from MCP, web, product, connector, stable
promotion, and concrete executor providers.  Callers should enter through the
application service or the command gateway exported here.
"""

from runner.work_item_governance.contracts import (
    CURRENT_LEDGER_SCHEMA_VERSION,
    TERMINAL_WORK_ITEM_STATES,
    WORK_ITEM_STATES,
    WORK_ITEM_TRANSITIONS,
)
from runner.work_item_governance.errors import WorkItemGovernanceError
from runner.work_item_governance.ids import new_stable_id, new_uuid7
from runner.work_item_governance.repository import SQLiteWorkItemLedger
from runner.work_item_governance.principal import PrincipalContext, trusted_principal_context
from runner.work_item_governance.service import WorkItemApplicationService
from runner.work_item_governance.schema_loader import validate_governance_record

__all__ = [
    "CURRENT_LEDGER_SCHEMA_VERSION",
    "TERMINAL_WORK_ITEM_STATES",
    "WORK_ITEM_STATES",
    "WORK_ITEM_TRANSITIONS",
    "WorkItemGovernanceError",
    "SQLiteWorkItemLedger",
    "WorkItemApplicationService",
    "PrincipalContext",
    "trusted_principal_context",
    "validate_governance_record",
    "new_stable_id",
    "new_uuid7",
]
