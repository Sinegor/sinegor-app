from datetime import UTC, datetime
from io import BytesIO
from uuid import UUID

import pytest
from pypdf import PdfReader

from sinegor.modules.destruction.documents import render_documents, snapshot


def event(subjects=None, basis="Истечение срока хранения"):
    return snapshot(
        operation_id=UUID("11111111-1111-1111-1111-111111111111"),
        kind="customer_fields",
        destroyed_at=datetime(2026, 11, 9, 22, 30, tzinfo=UTC),
        metadata={
            "subjects": subjects
            or [
                {
                    "identity": "Иванов Иван Иванович",
                    "categories": ["Номер телефона"],
                    "source": "customers.display_name",
                }
            ],
            "source": "Карточка заказчика",
            "basis": basis,
            "method": "Обнуление поля phone в PostgreSQL",
            "entity": {"customer_id": "22222222-2222-2222-2222-222222222222"},
            "initiator": "admin:33333333-3333-3333-3333-333333333333",
            "executor": "FastAPI",
        },
    )


def pdf_text(data):
    reader = PdfReader(BytesIO(data))
    for page in reader.pages:
        assert abs(float(page.mediabox.width) - 595.276) < 1
        assert abs(float(page.mediabox.height) - 841.89) < 1
    return "\n".join(page.extract_text() for page in reader.pages), len(reader.pages)


def test_act_and_independent_extract_share_five_frozen_fields_and_manual_spaces():
    frozen = event()
    files = render_documents(frozen)
    act, _ = pdf_text(files["act.pdf"])
    extract, _ = pdf_text(files["extract.pdf"])
    for text in [act, extract]:
        for value in [
            "Иванов Иван Иванович",
            "Номер телефона",
            "10.11.2026",
            "Истечение срока хранения",
            "SINEGOR LAB",
            str(frozen["operation_id"]),
        ]:
            assert value in text
    assert "Артемьев Дмитрий Валерьевич" in act
    for label in [
        "Адрес оператора",
        "Должность",
        "Подпись",
        "Лицо, осуществившее уничтожение персональных данных: Артемьев Дмитрий Валерьевич",
        "Не применимо",
        "Обнуление поля phone",
    ]:
        assert label in act
    assert "Акт об уничтожении персональных данных" in act
    assert "Выгрузка из журнала" in extract
    assert "Подпись" not in extract
    assert "Адрес оператора" not in extract


def test_unknown_reason_is_not_invented_or_added_to_frozen_extract():
    frozen = event(basis=None)
    files = render_documents(frozen)
    act, _ = pdf_text(files["act.pdf"])
    extract, _ = pdf_text(files["extract.pdf"])
    assert "Причина уничтожения" in act
    assert "Не зафиксирована в журнале" in extract
    assert frozen["basis"] is None


def test_batch_and_long_unbroken_identity_wrap_to_a4_without_dropping_last_subject():
    subjects = [
        {
            "identity": f"Субъект {i} " + "ДлинноеФИО" * 30,
            "categories": ["Адрес электронной почты", "Номер телефона"],
            "source": "synthetic",
        }
        for i in range(80)
    ]
    for data in render_documents(event(subjects)).values():
        text, pages = pdf_text(data)
        assert pages > 1
        assert "Субъект 79" in text
        assert "Номер телефона" in text


def test_missing_subject_blocks_generation_and_naive_confirmation_is_rejected():
    with pytest.raises(ValueError):
        snapshot(
            operation_id=UUID(int=1), kind="customer", destroyed_at=datetime.now(), metadata={}
        )
    with pytest.raises(ValueError):
        snapshot(
            operation_id=UUID(int=1),
            kind="customer",
            destroyed_at=datetime.now(UTC),
            metadata={"subjects": []},
        )


@pytest.mark.parametrize(
    "kind",
    [
        "disk_folder",
        "consultation_auto",
        "consultation_manual",
        "security_events",
        "customer_fields",
        "agreement",
        "order_history",
        "customer",
    ],
)
def test_act_uses_requested_fields_and_order_for_every_operation(kind):
    frozen = event()
    frozen["kind"] = kind
    act, _ = pdf_text(render_documents(frozen)["act.pdf"])
    compact = " ".join(act.split())
    fields = [
        "Номер акта:",
        "Дата уничтожения (московское время): 10.11.2026",
        "Идентификатор события реестра:",
        "Оператор: Артемьев Дмитрий Валерьевич",
        "Адрес оператора:",
        "Обработка по поручению оператора: Не применимо",
        "Субъект персональных данных: Иванов Иван Иванович",
        "Категории уничтоженных персональных данных: Номер телефона",
        "Информационная система:",
        "Способ уничтожения:",
        "Причина уничтожения:",
        "Лицо, осуществившее уничтожение персональных данных: Артемьев Дмитрий Валерьевич",
        "Должность:",
        "Подпись:",
    ]
    # Report booleans/positions on failure, never the document's contents.
    present = {label: label in compact for label in fields}
    assert present == dict.fromkeys(fields, True)
    positions = [compact.index(label) for label in fields]
    assert positions == sorted(positions)
    removed = ["Связанные документы:", "Источник данных:", "Носитель:", "ФИО:"]
    absent = {label: label not in compact for label in removed}
    assert absent == dict.fromkeys(removed, True)
    heading = "Акт об уничтожении персональных данных"
    # ReportLab writes the footer before the body in the PDF content stream.
    first_field = compact.partition(heading)[2].lstrip()
    number_follows_heading = first_field.startswith(fields[0])
    assert number_follows_heading


def test_batch_act_repeats_subject_and_categories_as_ordinary_fields():
    subjects = [
        {"identity": "Первый Субъект", "categories": ["Номер телефона"], "source": "test"},
        {
            "identity": "Второй Субъект",
            "categories": ["Адрес электронной почты"],
            "source": "test",
        },
    ]
    act, _ = pdf_text(render_documents(event(subjects))["act.pdf"])
    compact = " ".join(act.split())
    pairs = [
        "Субъект персональных данных: Первый Субъект "
        "Категории уничтоженных персональных данных: Номер телефона",
        "Субъект персональных данных: Второй Субъект "
        "Категории уничтоженных персональных данных: Адрес электронной почты",
    ]
    present = {index: pair in compact for index, pair in enumerate(pairs)}
    assert present == {0: True, 1: True}
    counts = (
        compact.count("Субъект персональных данных:"),
        compact.count("Категории уничтоженных персональных данных:"),
    )
    assert counts == (2, 2)
