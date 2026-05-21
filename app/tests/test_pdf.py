import fitz
import pytest

from app.pdf import PdfFillError, fill_pdf
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

def test_fill_real_word_exported_pdf() -> None:
    src = (FIXTURES / "contract.pdf").read_bytes()
    font = (FIXTURES / "arial.ttf").read_bytes()

    res = fill_pdf(
        src,
        {
            "customer_name": "OOO Romashka",
            "date": "2026-05-21",
            "total_sum": "12500.00 RUB",
        },
        fallback_font=lambda: font,
    )

    # Проверяем что placeholder'ы убраны из PDF
    result_doc = fitz.open(stream=res, filetype="pdf")
    for page in result_doc:
        # search_for работает надёжнее get_text для кастомных шрифтов
        assert not page.search_for("{{customer_name}}")
        assert not page.search_for("{{date}}")
        assert not page.search_for("{{total_sum}}")

    # И что PDF валидный
    assert res.startswith(b"%PDF")

def make_pdf_with_placeholders() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 90), "Customer: {{customer_name}}", fontsize=12)
    page.insert_text((50, 120), "Date: {{date}}", fontsize=12)
    return doc.tobytes()


def make_pdf_with_limited_space() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 90), "Customer: {{customer_name}} Date: {{date}}", fontsize=12)
    return doc.tobytes()


def make_pdf_without_placeholders() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 90), "Plain PDF without placeholders", fontsize=12)
    return doc.tobytes()


def make_pdf_with_regular_text() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 90), "Hello Andrey", fontsize=12)
    page.insert_text((50, 120), "Andrey signed the contract", fontsize=12)
    return doc.tobytes()


def extract_text(payload: bytes) -> str:
    doc = fitz.open(stream=payload, filetype="pdf")
    return "\n".join(page.get_text() for page in doc)


def test_fill_pdf_replaces_text_placeholders() -> None:
    src = make_pdf_with_placeholders()

    res = fill_pdf(
        src,
        {
            "customer_name": "OOO Romashka",
            "date": "2024-01-15",
        },
    )

    assert res.startswith(b"%PDF")

    text = extract_text(res)
    assert "{{customer_name}}" not in text
    assert "{{date}}" not in text
    assert "OOO Romashka" in text
    assert "2024-01-15" in text


def test_fill_pdf_replaces_all_occurrences() -> None:
    src = make_pdf_with_placeholders()

    res = fill_pdf(src, {"customer_name": "A", "date": "A"})

    text = extract_text(res)
    assert text.count("A") >= 2


def test_fill_pdf_replaces_regular_text() -> None:
    src = make_pdf_with_regular_text()

    res = fill_pdf(src, {}, replace={"Andrey": "Evgeny"})

    text = extract_text(res)
    assert "Andrey" not in text
    assert "Evgeny signed the contract" in text
    assert text.count("Evgeny") == 2


def test_fill_pdf_regular_text_not_found() -> None:
    src = make_pdf_with_regular_text()

    with pytest.raises(PdfFillError, match="Text to replace not found in PDF: Ivan"):
        fill_pdf(src, {}, replace={"Ivan": "Evgeny"})


def test_fill_pdf_without_matching_placeholders() -> None:
    src = make_pdf_without_placeholders()

    with pytest.raises(PdfFillError, match="PDF template has no placeholders"):
        fill_pdf(src, {"customer_name": "OOO Romashka"})


def test_fill_pdf_missing_value() -> None:
    src = make_pdf_with_placeholders()

    with pytest.raises(PdfFillError, match="Missing values for PDF placeholders: date"):
        fill_pdf(src, {"customer_name": "OOO Romashka"})


def test_fill_pdf_reports_value_that_cannot_fit() -> None:
    src = make_pdf_with_limited_space()

    with pytest.raises(PdfFillError, match="Value does not fit placeholder: customer_name"):
        fill_pdf(
            src,
            {
                "customer_name": "A" * 500,
                "date": "2026-05-20",
            },
        )


def test_fill_pdf_broken_pdf() -> None:
    with pytest.raises(PdfFillError, match="Failed to open PDF template"):
        fill_pdf(b"not a pdf", {"customer_name": "OOO Romashka"})


def test_fill_pdf_data_and_replace_together() -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 90), "Customer: {{customer_name}}", fontsize=12)
    page.insert_text((50, 120), "Hello Andrey", fontsize=12)
    src = doc.tobytes()

    res = fill_pdf(
        src,
        data={"customer_name": "OOO Romashka"},
        replace={"Andrey": "Evgeny"},
    )

    text = extract_text(res)
    assert "{{customer_name}}" not in text
    assert "OOO Romashka" in text
    assert "Andrey" not in text
    assert "Evgeny" in text