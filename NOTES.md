# Project Notes

## F14 Decision: document.list audit scope

**Decision**: `list_documents` endpoint (GET `/orgs/{org_id}/documents`) is explicitly **out of scope** for audit logging.

**Rationale**:
- List operations are high-frequency, read-only, and typically used for UI pagination/navigation
- Auditing every list request would generate excessive audit log volume with low security value
- The audit trail for individual document access (`document.view`) provides sufficient traceability
- This aligns with common practice where list/index endpoints are not audited, only detail/read endpoints

If list-level auditing is ever required, a separate `document.list` action with `resource_id_param="org_id"` can be added.