from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.core.v2_documents import DEMO_SEED
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def _signup(client: TestClient) -> tuple[str, dict[str, str]]:
    email = random_email()
    password = random_lower_string()

    response = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json={
            "email": email,
            "password": password,
            "full_name": "V2 Documents Tester",
        },
    )
    assert 200 <= response.status_code < 300, response.text

    headers = user_authentication_headers(
        client=client, email=email, password=password
    )

    return email, headers


def test_v2_documents_list_seeds_demo_lazily(client: TestClient) -> None:
    _, headers = _signup(client)

    # Without demo=true the user starts with zero documents.
    live = client.get("/api/v1/v2/documents/", headers=headers)
    assert live.status_code == 200, live.text
    assert live.json()["count"] == 0

    # First demo call lazily seeds the catalog.
    first = client.get("/api/v1/v2/documents/?demo=true", headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["count"] == len(DEMO_SEED)
    titles = {doc["title"] for doc in first.json()["data"]}
    assert {seed["title"] for seed in DEMO_SEED} <= titles

    # Repeat call is idempotent — no duplicates.
    second = client.get("/api/v1/v2/documents/?demo=true", headers=headers)
    assert second.status_code == 200, second.text
    assert second.json()["count"] == len(DEMO_SEED)


def test_v2_documents_create_update_get(client: TestClient) -> None:
    _, headers = _signup(client)

    created = client.post(
        "/api/v1/v2/documents/",
        headers=headers,
        json={
            "title": "Drafted document",
            "description": "Started in the library, fleshed out inline.",
            "human_summary": "Initial summary.",
            "collaborators": ["Tester"],
        },
    )
    assert created.status_code == 201, created.text
    document_id = created.json()["id"]
    assert created.json()["title"] == "Drafted document"
    assert created.json()["is_demo"] is False

    fetched = client.get(
        f"/api/v1/v2/documents/{document_id}", headers=headers
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["description"] == (
        "Started in the library, fleshed out inline."
    )

    updated = client.patch(
        f"/api/v1/v2/documents/{document_id}",
        headers=headers,
        json={"human_summary": "Edited inline."},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["human_summary"] == "Edited inline."
    assert updated.json()["title"] == "Drafted document"

    empty_update = client.patch(
        f"/api/v1/v2/documents/{document_id}",
        headers=headers,
        json={},
    )
    assert empty_update.status_code == 422, empty_update.text


def test_v2_document_folders_can_organize_documents(
    client: TestClient,
) -> None:
    _, headers = _signup(client)

    folder = client.post(
        "/api/v1/v2/documents/folders/",
        headers=headers,
        json={"name": "Customer incidents"},
    )
    assert folder.status_code == 201, folder.text
    folder_id = folder.json()["id"]
    assert folder.json()["visibility"] == "private"

    folders = client.get("/api/v1/v2/documents/folders/", headers=headers)
    assert folders.status_code == 200, folders.text
    assert folders.json()["count"] == 1
    assert folders.json()["data"][0]["name"] == "Customer incidents"

    created = client.post(
        "/api/v1/v2/documents/",
        headers=headers,
        json={"title": "Filed document", "folder_id": folder_id},
    )
    assert created.status_code == 201, created.text
    document_id = created.json()["id"]
    assert created.json()["folder_id"] == folder_id
    assert created.json()["folder_name"] == "Customer incidents"

    moved = client.patch(
        f"/api/v1/v2/documents/{document_id}",
        headers=headers,
        json={"folder_id": None},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["folder_id"] is None
    assert moved.json()["folder_name"] is None

    renamed = client.patch(
        f"/api/v1/v2/documents/folders/{folder_id}",
        headers=headers,
        json={"name": "Escalations"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Escalations"


def test_v2_document_folders_can_be_nested(client: TestClient) -> None:
    _, headers = _signup(client)

    parent = client.post(
        "/api/v1/v2/documents/folders/",
        headers=headers,
        json={"name": "Customers"},
    )
    assert parent.status_code == 201, parent.text
    parent_id = parent.json()["id"]
    assert parent.json()["parent_folder_id"] is None

    child = client.post(
        "/api/v1/v2/documents/folders/",
        headers=headers,
        json={"name": "Acme", "parent_folder_id": parent_id},
    )
    assert child.status_code == 201, child.text
    child_id = child.json()["id"]
    assert child.json()["parent_folder_id"] == parent_id

    root_move = client.patch(
        f"/api/v1/v2/documents/folders/{child_id}",
        headers=headers,
        json={"parent_folder_id": None},
    )
    assert root_move.status_code == 200, root_move.text
    assert root_move.json()["parent_folder_id"] is None

    nested_move = client.patch(
        f"/api/v1/v2/documents/folders/{child_id}",
        headers=headers,
        json={"parent_folder_id": parent_id},
    )
    assert nested_move.status_code == 200, nested_move.text
    assert nested_move.json()["parent_folder_id"] == parent_id


def test_v2_document_folders_reject_parent_cycles(client: TestClient) -> None:
    _, headers = _signup(client)

    parent = client.post(
        "/api/v1/v2/documents/folders/",
        headers=headers,
        json={"name": "Parent"},
    )
    assert parent.status_code == 201, parent.text
    parent_id = parent.json()["id"]

    child = client.post(
        "/api/v1/v2/documents/folders/",
        headers=headers,
        json={"name": "Child", "parent_folder_id": parent_id},
    )
    assert child.status_code == 201, child.text
    child_id = child.json()["id"]

    self_parent = client.patch(
        f"/api/v1/v2/documents/folders/{parent_id}",
        headers=headers,
        json={"parent_folder_id": parent_id},
    )
    assert self_parent.status_code == 422, self_parent.text

    descendant_parent = client.patch(
        f"/api/v1/v2/documents/folders/{parent_id}",
        headers=headers,
        json={"parent_folder_id": child_id},
    )
    assert descendant_parent.status_code == 422, descendant_parent.text


def test_v2_documents_can_be_favorited(client: TestClient) -> None:
    _, headers = _signup(client)

    created = client.post(
        "/api/v1/v2/documents/",
        headers=headers,
        json={"title": "Favorite me"},
    )
    assert created.status_code == 201, created.text
    document_id = created.json()["id"]
    assert created.json()["is_favorite"] is False

    favorited = client.put(
        f"/api/v1/v2/documents/{document_id}/favorite",
        headers=headers,
    )
    assert favorited.status_code == 200, favorited.text
    assert favorited.json()["is_favorite"] is True

    documents = client.get("/api/v1/v2/documents/", headers=headers)
    assert documents.status_code == 200, documents.text
    assert documents.json()["data"][0]["is_favorite"] is True

    unfavorited = client.delete(
        f"/api/v1/v2/documents/{document_id}/favorite",
        headers=headers,
    )
    assert unfavorited.status_code == 200, unfavorited.text
    assert unfavorited.json()["is_favorite"] is False


def test_v2_documents_are_scoped_to_owner(client: TestClient) -> None:
    _, owner_headers = _signup(client)
    _, intruder_headers = _signup(client)

    created = client.post(
        "/api/v1/v2/documents/",
        headers=owner_headers,
        json={"title": "Owner-only document"},
    )
    assert created.status_code == 201, created.text
    document_id = created.json()["id"]

    forbidden = client.get(
        f"/api/v1/v2/documents/{document_id}", headers=intruder_headers
    )
    assert forbidden.status_code == 404, forbidden.text

    intruder_patch = client.patch(
        f"/api/v1/v2/documents/{document_id}",
        headers=intruder_headers,
        json={"title": "Hijacked"},
    )
    assert intruder_patch.status_code == 404, intruder_patch.text


def test_v2_documents_can_be_shared_with_one_organization(
    client: TestClient,
    db: Session,
) -> None:
    owner_email, owner_headers = _signup(client)
    member_email, member_headers = _signup(client)

    owner = crud.get_user_by_email(session=db, email=owner_email)
    member = crud.get_user_by_email(session=db, email=member_email)
    assert owner is not None
    assert member is not None
    assert owner.organization_id is not None
    assert owner.organization_role == "admin"
    assert member.organization_id is not None
    assert member.organization_id != owner.organization_id
    assert member.organization_role == "admin"

    invite = client.post(
        "/api/v1/organizations/invitations",
        headers=owner_headers,
        json={"email": member_email},
    )
    assert invite.status_code == 201, invite.text

    accepted = client.post(
        f"/api/v1/organizations/invitations/{invite.json()['id']}/accept",
        headers=member_headers,
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["id"] == str(owner.organization_id)
    assert accepted.json()["organization_role"] == "member"

    db.refresh(member)
    assert member.organization_id == owner.organization_id
    assert member.organization_role == "member"

    private_doc = client.post(
        "/api/v1/v2/documents/",
        headers=owner_headers,
        json={"title": "Private owner document"},
    )
    assert private_doc.status_code == 201, private_doc.text
    assert private_doc.json()["visibility"] == "private"
    assert private_doc.json()["organization_id"] is None

    hidden = client.get(
        f"/api/v1/v2/documents/{private_doc.json()['id']}",
        headers=member_headers,
    )
    assert hidden.status_code == 404, hidden.text

    shared_doc = client.post(
        "/api/v1/v2/documents/",
        headers=owner_headers,
        json={
            "title": "Organization runbook",
            "visibility": "organization",
        },
    )
    assert shared_doc.status_code == 201, shared_doc.text
    document_id = shared_doc.json()["id"]
    assert shared_doc.json()["organization_id"] == str(owner.organization_id)
    assert shared_doc.json()["visibility"] == "organization"

    listed = client.get("/api/v1/v2/documents/", headers=member_headers)
    assert listed.status_code == 200, listed.text
    assert {doc["id"] for doc in listed.json()["data"]} == {document_id}

    member_patch = client.patch(
        f"/api/v1/v2/documents/{document_id}",
        headers=member_headers,
        json={"human_summary": "Updated by another organization member."},
    )
    assert member_patch.status_code == 200, member_patch.text
    assert member_patch.json()["human_summary"] == (
        "Updated by another organization member."
    )

    visibility_patch = client.patch(
        f"/api/v1/v2/documents/{document_id}",
        headers=member_headers,
        json={"visibility": "private"},
    )
    assert visibility_patch.status_code == 403, visibility_patch.text


def test_v2_document_can_be_shared_with_specific_org_member_as_editor(
    client: TestClient,
    db: Session,
) -> None:
    owner_email, owner_headers = _signup(client)
    member_email, member_headers = _signup(client)

    owner = crud.get_user_by_email(session=db, email=owner_email)
    member = crud.get_user_by_email(session=db, email=member_email)
    assert owner is not None
    assert member is not None

    invite = client.post(
        "/api/v1/organizations/invitations",
        headers=owner_headers,
        json={"email": member_email},
    )
    assert invite.status_code == 201, invite.text
    accepted = client.post(
        f"/api/v1/organizations/invitations/{invite.json()['id']}/accept",
        headers=member_headers,
    )
    assert accepted.status_code == 200, accepted.text
    db.refresh(member)

    created = client.post(
        "/api/v1/v2/documents/",
        headers=owner_headers,
        json={"title": "Member-specific draft"},
    )
    assert created.status_code == 201, created.text
    document_id = created.json()["id"]
    assert created.json()["visibility"] == "private"

    hidden = client.get(
        f"/api/v1/v2/documents/{document_id}", headers=member_headers
    )
    assert hidden.status_code == 404, hidden.text

    shares = client.put(
        f"/api/v1/v2/documents/{document_id}/shares/",
        headers=owner_headers,
        json={"shares": [{"user_id": str(member.id), "permission": "editor"}]},
    )
    assert shares.status_code == 200, shares.text
    assert shares.json()["count"] == 1
    assert shares.json()["data"][0]["email"] == member_email
    assert shares.json()["data"][0]["permission"] == "editor"

    listed = client.get("/api/v1/v2/documents/", headers=member_headers)
    assert listed.status_code == 200, listed.text
    assert {doc["id"] for doc in listed.json()["data"]} == {document_id}
    assert listed.json()["data"][0]["user_access"] == "editor"

    member_patch = client.patch(
        f"/api/v1/v2/documents/{document_id}",
        headers=member_headers,
        json={"human_summary": "Edited by an assigned member."},
    )
    assert member_patch.status_code == 200, member_patch.text
    assert member_patch.json()["human_summary"] == "Edited by an assigned member."

    member_visibility_patch = client.patch(
        f"/api/v1/v2/documents/{document_id}",
        headers=member_headers,
        json={"visibility": "organization"},
    )
    assert member_visibility_patch.status_code == 403, member_visibility_patch.text


def test_v2_document_viewer_share_is_read_only(
    client: TestClient,
    db: Session,
) -> None:
    owner_email, owner_headers = _signup(client)
    member_email, member_headers = _signup(client)

    owner = crud.get_user_by_email(session=db, email=owner_email)
    member = crud.get_user_by_email(session=db, email=member_email)
    assert owner is not None
    assert member is not None

    invite = client.post(
        "/api/v1/organizations/invitations",
        headers=owner_headers,
        json={"email": member_email},
    )
    assert invite.status_code == 201, invite.text
    accepted = client.post(
        f"/api/v1/organizations/invitations/{invite.json()['id']}/accept",
        headers=member_headers,
    )
    assert accepted.status_code == 200, accepted.text
    db.refresh(member)

    created = client.post(
        "/api/v1/v2/documents/",
        headers=owner_headers,
        json={"title": "Read-only member document"},
    )
    assert created.status_code == 201, created.text
    document_id = created.json()["id"]

    shares = client.put(
        f"/api/v1/v2/documents/{document_id}/shares/",
        headers=owner_headers,
        json={"shares": [{"user_id": str(member.id), "permission": "viewer"}]},
    )
    assert shares.status_code == 200, shares.text

    fetched = client.get(
        f"/api/v1/v2/documents/{document_id}", headers=member_headers
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["user_access"] == "viewer"

    blocked_patch = client.patch(
        f"/api/v1/v2/documents/{document_id}",
        headers=member_headers,
        json={"human_summary": "Should not save."},
    )
    assert blocked_patch.status_code == 403, blocked_patch.text


def test_v2_document_share_rejects_users_outside_owner_org(
    client: TestClient,
    db: Session,
) -> None:
    _, owner_headers = _signup(client)
    outsider_email, _ = _signup(client)
    outsider = crud.get_user_by_email(session=db, email=outsider_email)
    assert outsider is not None

    created = client.post(
        "/api/v1/v2/documents/",
        headers=owner_headers,
        json={"title": "Internal-only document"},
    )
    assert created.status_code == 201, created.text

    blocked = client.put(
        f"/api/v1/v2/documents/{created.json()['id']}/shares/",
        headers=owner_headers,
        json={"shares": [{"user_id": str(outsider.id), "permission": "editor"}]},
    )
    assert blocked.status_code == 422, blocked.text


def test_v2_document_org_visibility_uses_current_user_org(client: TestClient) -> None:
    _, headers = _signup(client)

    created = client.post(
        "/api/v1/v2/documents/",
        headers=headers,
        json={"title": "Shared in personal org", "visibility": "organization"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["visibility"] == "organization"
    assert created.json()["organization_id"] is not None
