from app.core.metrics.tokens import (
    count_details_sections_tokens,
    count_paragraph_tokens,
)
from app.models import (
    V2DocumentDetailsSection,
    V2DocumentParagraph,
    V2DocumentSegment,
)


def test_token_counts_accept_dicts_and_typed_document_models() -> None:
    paragraph_dict = {"segments": [{"text": "12345678"}]}
    paragraph_model = V2DocumentParagraph(segments=[V2DocumentSegment(text="abcdefgh")])
    section_dict = {"anchor_id": "dict", "markdown": "12345678"}
    section_model = V2DocumentDetailsSection(
        anchor_id="model",
        markdown="abcdefgh",
    )

    assert count_paragraph_tokens([paragraph_dict, paragraph_model]) == 4
    assert count_details_sections_tokens([section_dict, section_model]) == 4
