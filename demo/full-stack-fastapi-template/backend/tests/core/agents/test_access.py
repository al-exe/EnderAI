import uuid

from app.core.agents.access import build_agent_specialist_acl_filter
from app.models import User


def _user(**kwargs: object) -> User:
    return User(
        id=kwargs.pop("id", uuid.uuid4()),
        email=f"{uuid.uuid4()}@example.com",
        **kwargs,
    )


def test_agent_acl_demo_only_returns_demo_specialists() -> None:
    actor = _user()
    expression = build_agent_specialist_acl_filter(actor, demo=True)

    assert str(expression).lower().find("agent_specialist.is_demo") >= 0


def test_agent_acl_owner_clause_matches_private_specialists() -> None:
    actor = _user()
    expression = build_agent_specialist_acl_filter(actor, demo=False)

    assert str(expression).find("agent_specialist.owner_id") >= 0
    assert str(expression).find("agent_specialist.is_demo") >= 0


def test_agent_acl_org_clause_available_for_org_member() -> None:
    actor = _user(organization_id=uuid.uuid4(), organization_role="member")
    expression = build_agent_specialist_acl_filter(actor, demo=False)

    rendered = str(expression)
    assert "agent_specialist.visibility" in rendered
    assert "agent_specialist.organization_id" in rendered
