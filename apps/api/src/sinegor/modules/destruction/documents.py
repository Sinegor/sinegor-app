"""Two A4 documents from one frozen event; never query the destroyed source."""

from datetime import datetime
from io import BytesIO
from pathlib import Path
from uuid import UUID
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

SYSTEM = "SINEGOR LAB — система учёта заказчиков и заказов"
OPERATOR = "Артемьев Дмитрий Валерьевич"
FONT = "SinegorEvidence"
pdfmetrics.registerFont(TTFont(FONT, str(Path(__file__).parent / "assets" / "DejaVuSans.ttf")))


def snapshot(*, operation_id: UUID, kind: str, destroyed_at: datetime, metadata: dict) -> dict:
    if destroyed_at.tzinfo is None or destroyed_at.utcoffset() is None:
        raise ValueError("Confirmation timestamp must be aware")
    subjects = metadata.get("subjects")
    if not isinstance(subjects, list) or not subjects:
        raise ValueError("Subject metadata is required")
    for subject in subjects:
        if (
            not subject.get("identity")
            or not subject.get("source")
            or not subject.get("categories")
        ):
            raise ValueError("Incomplete subject metadata")
    if not metadata.get("method") or not metadata.get("source"):
        raise ValueError("Source and actual destruction method are required")
    return {
        "version": 1,
        "operation_id": str(operation_id),
        "act_number": str(operation_id),
        "kind": kind,
        "destroyed_at": destroyed_at.isoformat(),
        "date_moscow": destroyed_at.astimezone(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y"),
        "system": SYSTEM,
        "operator": OPERATOR,
        "subjects": subjects,
        "basis": metadata.get("basis"),
        "method": metadata["method"],
        "source": metadata["source"],
        "entity": metadata.get("entity", {}),
        "initiator": metadata.get("initiator"),
        "executor": metadata.get("executor"),
    }


def _pdf(event: dict, *, extract: bool) -> bytes:
    output = BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=42,
        invariant=1,
        title="Выгрузка из журнала" if extract else "Акт об уничтожении персональных данных",
        author=OPERATOR,
    )
    normal = ParagraphStyle(
        "normal", fontName=FONT, fontSize=9, leading=13, spaceAfter=8, splitLongWords=True
    )
    title = ParagraphStyle(
        "title", parent=normal, fontSize=13, leading=18, alignment=TA_CENTER, spaceAfter=14
    )

    def p(value, style=normal):
        return Paragraph(escape(str(value)).replace("\n", "<br/>"), style)

    heading = (
        "Выгрузка из журнала регистрации событий уничтожения персональных данных"
        if extract
        else "Акт об уничтожении персональных данных"
    )
    story = [
        p(heading, title),
        p(f"Номер акта: {event['act_number']}"),
    ]
    if not extract:
        story.append(p(f"Дата уничтожения (московское время): {event['date_moscow']}"))
    story += [
        p(f"Идентификатор события реестра: {event['operation_id']}"),
    ]
    if extract:
        story.append(p("Связанные документы: act.pdf — акт; extract.pdf — выгрузка из журнала."))
    if not extract:
        story += [
            p(f"Оператор: {event['operator']}"),
            p("Адрес оператора: ________________________________________________________"),
            p("________________________________________________________________________"),
            p("Обработка по поручению оператора: Не применимо"),
        ]
        for subject in event["subjects"]:
            story += [
                p(f"Субъект персональных данных: {subject['identity']}"),
                p(
                    "Категории уничтоженных персональных данных: "
                    + "; ".join(subject["categories"])
                ),
            ]
    story += [
        p(f"Информационная система: {event['system']}"),
    ]
    if extract:
        story.append(p(f"Дата уничтожения (московское время): {event['date_moscow']}"))
    else:
        story.append(p(f"Способ уничтожения: {event['method']}"))
    basis = event["basis"] or (
        "Не зафиксирована в журнале"
        if extract
        else "________________________________________________________"
    )
    story.append(p(f"Причина уничтожения: {basis}"))
    if extract:
        rows = [[p("Субъект персональных данных"), p("Категории уничтоженных ПДн")]]
        for subject in event["subjects"]:
            # Separate flowing rows allow even a single very long subject to cross page boundaries.
            rows.append([p(subject["identity"]), p("; ".join(subject["categories"]))])
        table = LongTable(
            rows, colWidths=[270, A4[0] - 72 - 270], repeatRows=1, splitInRow=1, hAlign="LEFT"
        )
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story += [Spacer(1, 6), table, Spacer(1, 15)]
    if not extract:
        story += [
            p(f"Лицо, осуществившее уничтожение персональных данных: {OPERATOR}"),
            p("Должность: ______________________________________________________________"),
            p("Подпись: ______________________________"),
            p(
                "Электронная форма подготовлена приложением. Бумажный экземпляр дополняется, "
                "подписывается и хранится оператором вне приложения."
            ),
        ]
    else:
        story += [
            p(
                "Зафиксированная выгрузка события. Сведения об уничтоженных данных "
                "сохранены до очистки источника. Электронный документ не изменяется "
                "при последующем рукописном дополнении бумажного акта."
            )
        ]

    def footer(canvas, document):
        canvas.setFont(FONT, 7)
        canvas.drawString(36, 25, f"Событие {event['operation_id']}")
        canvas.drawRightString(A4[0] - 36, 25, f"Страница {document.page}")

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()


def render_documents(event: dict) -> dict[str, bytes]:
    return {"act.pdf": _pdf(event, extract=False), "extract.pdf": _pdf(event, extract=True)}
