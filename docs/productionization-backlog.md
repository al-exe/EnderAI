# Productionization Backlog

## Focus Areas

The current productionization focus is:

- hardening the canonical Topic / Case / ContextPack stack
- keeping backend, frontend, and MCP behavior aligned
- improving operability, validation, and observability around the canonical model

## Current Priorities

### 1. Deployment coordination

Backend and frontend deploys should remain coordinated because the frontend depends on the canonical Topic and Case endpoints.

### 2. MCP workflow validation

The hosted MCP workflow should continue validating case sequencing and surfacing clear operator-facing errors for invalid transitions.

### 3. Schema and migration hygiene

All schema changes should continue to land through Alembic migrations and explicit operator workflows rather than startup-time mutations.

### 4. Release verification

Release checks should confirm:

- frontend build success
- backend route health
- MCP package build/test success
- zero active runtime references to retired product-domain concepts

### 5. Observability

Case event auditing, health checks, and deployment verification should remain part of the standard operator workflow.
