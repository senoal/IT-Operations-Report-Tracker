import sqlite3
import re
import uuid
import io
from datetime import datetime
from pathlib import Path

import pdfplumber
from flask import Flask, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename


app = Flask(__name__)
app.config["SECRET_KEY"] = "report-tracker-local-development"
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
DATABASE_PATH = Path(__file__).parent / "data" / "report_tracker.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"
UPLOAD_PATH = Path(__file__).parent / "instance" / "uploads"
REPORT_FIELDS = (
    "report_period", "department", "report_id", "report_date", "generated_time",
    "report_status", "primary_application", "supporting_server", "supporting_system",
    "reporting_cycle", "application_availability", "total_incidents",
    "identity_tickets", "sla_compliance",
)
FIELD_LABELS = {
    "report_period": "Report Period", "department": "Department", "report_id": "Report ID",
    "report_date": "Report Date", "generated_time": "Generated Time", "report_status": "Report Status",
    "primary_application": "Primary Application", "supporting_server": "Supporting Server",
    "supporting_system": "Supporting System", "reporting_cycle": "Reporting Cycle",
    "application_availability": "Application Availability", "total_incidents": "Total Incidents",
    "identity_tickets": "Identity Tickets", "sla_compliance": "SLA Compliance",
}


def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_database():
    """Create the tracker database and its schema without adding sample reports."""
    DATABASE_PATH.parent.mkdir(exist_ok=True)
    with get_connection() as connection:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        columns = {row[1] for row in connection.execute("PRAGMA table_info(reports)")}
        if "application_tickets" in columns and "identity_tickets" not in columns:
            connection.execute("ALTER TABLE reports RENAME COLUMN application_tickets TO identity_tickets")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(reports)")}
        for column, definition in (
            ("source_filename", "TEXT"),
            ("source_mime_type", "TEXT"),
            ("source_pdf", "BLOB"),
        ):
            if column not in columns:
                connection.execute(f"ALTER TABLE reports ADD COLUMN {column} {definition}")


def extract_pdf_text(pdf_path):
    """Read native text first, then use OCR for image-only reports."""
    with pdfplumber.open(pdf_path) as document:
        text = "\n".join(page.extract_text() or "" for page in document.pages)
    if text.strip():
        return text

    try:
        import easyocr
        import fitz

        reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        document = fitz.open(pdf_path)
        lines = []
        for number, page in enumerate(document):
            image_path = UPLOAD_PATH / f"ocr-{uuid.uuid4()}-{number}.png"
            page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(image_path)
            lines.extend(reader.readtext(str(image_path), detail=0, paragraph=True))
            image_path.unlink(missing_ok=True)
        return "\n".join(lines)
    except Exception as error:
        raise ValueError("PDF tidak memiliki teks yang dapat dibaca dan OCR belum dapat dijalankan.") from error


def extract_report_fields(pdf_path):
    text = extract_pdf_text(pdf_path)
    compact = re.sub(r"\s+", " ", text).strip()
    labels = "|".join(re.escape(label) for label in FIELD_LABELS.values())
    values = {field: "" for field in REPORT_FIELDS}

    for field, label in FIELD_LABELS.items():
        match = re.search(rf"{re.escape(label)}\s*[:\-]?\s*(.+?)(?=\s+(?:{labels})\b|$)", compact, re.IGNORECASE)
        if match:
            values[field] = match.group(1).strip(" :|-\t")

    for field, label in FIELD_LABELS.items():
        if field in {"application_availability", "total_incidents", "identity_tickets", "sla_compliance"}:
            after = re.search(rf"{re.escape(label)}\s*[:\-]?\s*([0-9]+(?:[.,][0-9]+)?%?)", compact, re.IGNORECASE)
            before = re.search(rf"([0-9]+(?:[.,][0-9]+)?%?)\s*{re.escape(label)}", compact, re.IGNORECASE)
            metric = after or before
            if metric:
                values[field] = metric.group(1).replace(",", ".").replace("%", "")

    # Each report presents its headline KPIs as values followed by labels. Two
    # approved layouts occur in the supplied report family; parse the complete
    # group to avoid assigning a neighbouring value to the wrong field.
    number = r"([0-9]+(?:[.,][0-9]+)?%?)"
    ticket_label = r"(?:Application|Service Desk|Support|Identity) Tickets"
    incident_first = re.search(
        rf"{number}\s+{number}\s+{number}\s+{number}\s+Application Availability\s+Total Incidents\s+{ticket_label}\s+SLA Compliance",
        compact, re.IGNORECASE,
    )
    tickets_first = re.search(
        rf"{number}\s+{number}\s+{number}\s+{number}\s+Application Availability\s+{ticket_label}\s+SLA Compliance\s+Total Incidents",
        compact, re.IGNORECASE,
    )
    if incident_first:
        values.update({
            "application_availability": incident_first.group(1).replace(",", ".").replace("%", ""),
            "total_incidents": incident_first.group(2),
            "identity_tickets": incident_first.group(3),
            "sla_compliance": incident_first.group(4).replace(",", ".").replace("%", ""),
        })
    elif tickets_first:
        values.update({
            "application_availability": tickets_first.group(1).replace(",", ".").replace("%", ""),
            "identity_tickets": tickets_first.group(2),
            "sla_compliance": tickets_first.group(3).replace(",", ".").replace("%", ""),
            "total_incidents": tickets_first.group(4),
        })

    # Report IDs use a fixed, unambiguous operational format. Prioritising this
    # avoids accidental capture of adjacent table labels or dates.
    report_id = re.search(r"\bITOPS[\s-]*MON[\s-]*\d{4}[\s-]*\d{2}[\s-]*\d{3}\b", compact, re.IGNORECASE)
    if report_id:
        values["report_id"] = re.sub(r"[\s-]+", "-", report_id.group(0)).upper()

    # A report may render the value either after or before its table label.
    # Limit accepted values to defined reporting cycles instead of using a
    # neighbouring field as the generic table parser can do.
    cycle_after = re.search(r"Reporting\s*Cycle\s*[:\-]?\s*(Monthly|Weekly|Quarterly|Annually|Annual)", compact, re.IGNORECASE)
    cycle_before = re.search(r"\b(Monthly|Weekly|Quarterly|Annually|Annual)\s+Reporting\s*Cycle\b", compact, re.IGNORECASE)
    cycle = cycle_after or cycle_before
    if cycle:
        values["reporting_cycle"] = cycle.group(1).title()

    # Fallback labels used by system-focused reports. The boundaries keep each
    # value isolated when a PDF exports two metadata pairs on one visual row.
    system_metadata_patterns = {
        "report_status": r"Report\s+Status\s+(.+?)(?=\s+(?:Primary\s+System|Primary\s+Application|Supporting\s+Server|Supported\s+Application|Reporting\s+Cycle)\b|$)",
        "supporting_server": r"Supporting\s+Server\s+(.+?)(?=\s+(?:Supported\s+Application|Supporting\s+System|Reporting\s+Cycle)\b|$)",
        "primary_application": r"Supported\s+Application\s+(.+?)(?=\s+(?:Reporting\s+Cycle|Executive\s+Summary)\b|$)",
        "supporting_system": r"Primary\s+System\s+(.+?)(?=\s+(?:Supporting\s+Server|Supported\s+Application|Reporting\s+Cycle)\b|$)",
        "identity_tickets": r"(?:Support\s+Queue\s+Received|Total\s+Tickets)\s*[:\-]?\s*([0-9]+)(?=\s*(?:tickets?|and|$))",
    }
    for field, pattern in system_metadata_patterns.items():
        extracted = re.search(pattern, compact, re.IGNORECASE)
        if extracted:
            values[field] = extracted.group(1).strip()

    # System-focused reports can include an explicit, authoritative key-value
    # section. Prefer it only when its own heading is present, so the existing
    # application-focused report patterns remain unchanged.
    structured_match = re.search(r"Structured\s+Extraction\s+Reference\s*(.*)", text, re.IGNORECASE | re.DOTALL)
    if structured_match:
        structured_text = structured_match.group(1)
        structured_labels = {
            "report_period": "report_period", "department": "department", "report_id": "report_id",
            "report_date": "report_date", "generated_time": "generated_time",
            "application_name": "primary_application", "server_name": "supporting_server",
            "system_name": "supporting_system", "application_availability": "application_availability",
            "total_incidents": "total_incidents", "total_tickets": "identity_tickets",
            "sla_compliance": "sla_compliance",
            # Newer tracker-ready reports use concise keys in the same
            # authoritative section. They are aliases, not replacements for
            # the established labels above.
            "availability": "application_availability", "incidents": "total_incidents",
            "tickets": "identity_tickets",
        }
        for source_label, destination in structured_labels.items():
            extracted = re.search(rf"(?im)^\s*{re.escape(source_label)}\s+(.+?)\s*$", structured_text)
            if extracted:
                value = extracted.group(1).strip()
                if destination in {"application_availability", "sla_compliance"}:
                    value = value.replace("%", "").replace(",", ".")
                values[destination] = value

        # The source metadata is laid out in pairs on one row. These bounded
        # matches prevent a neighbouring label from becoming part of a value.
    return values


def save_report(record, source_filename=None, source_pdf=None):
    """Validate and persist the 14 report values defined by the input specification."""
    normalized = {field: str(record[field]).strip() for field in REPORT_FIELDS}
    if any(not value for value in normalized.values()):
        raise ValueError

    availability = float(normalized["application_availability"].replace("%", "").replace(",", "."))
    incidents = int(normalized["total_incidents"])
    tickets = int(normalized["identity_tickets"])
    sla = float(normalized["sla_compliance"].replace("%", "").replace(",", "."))
    if not 0 <= availability <= 100 or not 0 <= sla <= 100 or incidents < 0 or tickets < 0:
        raise ValueError

    date_formats = ("%d %B %Y", "%Y-%m-%d")
    parsed_date = next((datetime.strptime(normalized["report_date"], fmt) for fmt in date_formats if _matches_date(normalized["report_date"], fmt)), None)
    if not parsed_date:
        raise ValueError
    normalized["report_date"] = parsed_date.strftime("%d %B %Y")

    with get_connection() as connection:
        connection.execute(
            """INSERT INTO reports (
                report_period, department, report_id, report_date, generated_time, report_status,
                primary_application, supporting_server, supporting_system, reporting_cycle,
                application_availability, total_incidents, identity_tickets, sla_compliance,
                source_filename, source_mime_type, source_pdf
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            tuple(normalized[field] for field in REPORT_FIELDS[:10])
            + (availability, incidents, tickets, sla, source_filename, "application/pdf" if source_pdf else None, source_pdf),
        )


def _matches_date(value, date_format):
    try:
        datetime.strptime(value, date_format)
        return True
    except ValueError:
        return False


def dashboard_metrics():
    """Build dashboard KPIs from reports stored in the tracker database."""
    init_database()
    with get_connection() as connection:
        metrics = connection.execute(
            """
            SELECT
                COUNT(*) AS reports,
                COUNT(DISTINCT primary_application) AS applications,
                AVG(application_availability) AS availability,
                AVG(sla_compliance) AS sla,
                COALESCE(SUM(total_incidents), 0) AS incidents,
                COALESCE(SUM(identity_tickets), 0) AS tickets
            FROM reports
            """
        ).fetchone()

    return {
        "reports": metrics["reports"],
        "applications": metrics["applications"],
        "availability": f"{metrics['availability'] or 0:.2f}%",
        "sla": f"{metrics['sla'] or 0:.2f}%",
        "incidents": metrics["incidents"],
        "tickets": metrics["tickets"],
    }


def tracking_reports():
    """Group saved reports by application for the monthly tracking matrix."""
    init_database()
    month_names = {
        "january": 0, "januari": 0, "february": 1, "februari": 1, "march": 2, "maret": 2,
        "april": 3, "may": 4, "mei": 4, "june": 5, "juni": 5, "july": 6, "juli": 6,
        "august": 7, "agustus": 7, "september": 8, "october": 9, "oktober": 9,
        "november": 10, "december": 11, "desember": 11,
    }
    with get_connection() as connection:
        rows = connection.execute(
            """SELECT id, primary_application, report_id, report_period, report_date, report_status,
                      application_availability, sla_compliance, total_incidents, identity_tickets
               FROM reports ORDER BY report_date, primary_application"""
        ).fetchall()
    grouped = {}
    for row in rows:
        application = row["primary_application"]
        item = grouped.setdefault(application, {"name": application, "focus": row["report_id"], "months": {}})
        period = row["report_period"].lower()
        month = next((index for name, index in month_names.items() if name in period), None)
        year_match = re.search(r"\b(20\d{2})\b", row["report_period"] or "")
        year = year_match.group(1) if year_match else "Tanpa Tahun"
        if month is not None:
            item["months"][f"{year}-{month}"] = {
                "id": row["id"], "report_id": row["report_id"], "period": row["report_period"],
                "date": row["report_date"], "status": row["report_status"],
                "availability": row["application_availability"], "sla": row["sla_compliance"],
                "incidents": row["total_incidents"], "tickets": row["identity_tickets"],
            }
    return list(grouped.values())


@app.get("/")
def welcome():
    return render_template("welcome.html")


@app.get("/dashboard")
def dashboard():
    return render_template("dashboard.html", metrics=dashboard_metrics(), tracking_reports=tracking_reports())


@app.route("/input-data", methods=["GET", "POST"])
def input_data():
    init_database()
    form_data = request.form.to_dict()
    message = None
    error = None

    if request.method == "POST":
        required = (
            "report_period", "department", "report_id", "report_date", "generated_time",
            "report_status", "primary_application", "supporting_server", "supporting_system",
            "reporting_cycle", "application_availability", "total_incidents",
            "identity_tickets", "sla_compliance",
        )
        if any(not form_data.get(field, "").strip() for field in required):
            error = "Lengkapi seluruh field sebelum menyimpan laporan."
        else:
            try:
                save_report(form_data)
                return redirect(url_for("input_data", saved="1"))
            except sqlite3.IntegrityError:
                error = "Report ID sudah ada. Gunakan Report ID yang unik."
            except ValueError:
                error = "Pastikan nilai KPI valid: persentase 0–100, insiden dan tiket tidak negatif."

    if request.args.get("saved"):
        message = "Laporan berhasil disimpan ke database."
    return render_template("input_data.html", form_data=form_data, message=message, error=error)


@app.route("/upload-report", methods=["GET", "POST"])
def upload_report():
    if request.method == "GET":
        return render_template("upload_report.html", error=None)
    uploaded = request.files.get("report_file")
    if not uploaded or not uploaded.filename.lower().endswith(".pdf"):
        return render_template("upload_report.html", error="Pilih satu file PDF laporan terlebih dahulu."), 400

    UPLOAD_PATH.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    filename = secure_filename(uploaded.filename)
    file_path = UPLOAD_PATH / f"{token}.pdf"
    uploaded.save(file_path)
    try:
        values = extract_report_fields(file_path)
    except ValueError as error:
        file_path.unlink(missing_ok=True)
        return render_template("upload_report.html", error=str(error)), 422
    return render_template("report_preview.html", values=values, filename=filename, token=token, error=None)


@app.post("/save-report")
def save_uploaded_report():
    record = {field: request.form.get(field, "") for field in REPORT_FIELDS}
    token = request.form.get("token", "")
    try:
        if any(not value.strip() for value in record.values()):
            raise ValueError
        file_path = UPLOAD_PATH / f"{token}.pdf"
        if not file_path.exists():
            raise ValueError
        save_report(record, request.form.get("filename", "report.pdf"), file_path.read_bytes())
    except sqlite3.IntegrityError:
        return render_template("report_preview.html", values=record, filename=request.form.get("filename", ""), token=token, error="Report ID sudah ada. Periksa kembali data preview."), 409
    except ValueError:
        return render_template("report_preview.html", values=record, filename=request.form.get("filename", ""), token=token, error="Lengkapi seluruh field dengan nilai yang valid sebelum menyimpan."), 400
    (UPLOAD_PATH / f"{token}.pdf").unlink(missing_ok=True)
    return redirect(url_for("dashboard"))


@app.post("/cancel-upload")
def cancel_upload():
    token = request.form.get("token", "")
    (UPLOAD_PATH / f"{token}.pdf").unlink(missing_ok=True)
    return redirect(url_for("upload_report"))


@app.get("/reports")
def reports():
    init_database()
    query = request.args.get("q", "").strip()
    application = request.args.get("application", "").strip()
    status = request.args.get("status", "").strip()
    period = request.args.get("period", "").strip()
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = 10
    conditions, parameters = [], []
    if query:
        conditions.append("(report_id LIKE ? OR primary_application LIKE ? OR department LIKE ?)")
        parameters.extend([f"%{query}%"] * 3)
    if application:
        conditions.append("primary_application = ?")
        parameters.append(application)
    if status:
        conditions.append("report_status = ?")
        parameters.append(status)
    if period:
        conditions.append("report_period = ?")
        parameters.append(period)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    with get_connection() as connection:
        applications = [row[0] for row in connection.execute("SELECT DISTINCT primary_application FROM reports ORDER BY primary_application")]
        statuses = [row[0] for row in connection.execute("SELECT DISTINCT report_status FROM reports ORDER BY report_status")]
        periods = [row[0] for row in connection.execute("SELECT DISTINCT report_period FROM reports ORDER BY report_period DESC")]
        total_records = connection.execute(f"SELECT COUNT(*) FROM reports {where_clause}", parameters).fetchone()[0]
        total_pages = max((total_records + per_page - 1) // per_page, 1)
        page = min(page, total_pages)
        records = connection.execute(
            """SELECT id, report_id, report_period, report_date, primary_application,
                      report_status, application_availability, sla_compliance,
                      total_incidents, identity_tickets, source_filename,
                      strftime('%d/%m/%Y · %H:%M', created_at, 'localtime') AS created_at_display
               FROM reports """ + where_clause + " ORDER BY report_date DESC, id DESC LIMIT ? OFFSET ?",
            parameters + [per_page, (page - 1) * per_page],
        ).fetchall()
    return render_template(
        "reports.html", records=records, applications=applications, statuses=statuses, periods=periods,
        query=query, application=application, status=status, period=period, page=page,
        total_pages=total_pages, total_records=total_records,
    )


@app.get("/reports/<int:record_id>")
def view_report(record_id):
    init_database()
    with get_connection() as connection:
        record = connection.execute("SELECT * FROM reports WHERE id = ?", (record_id,)).fetchone()
    if not record:
        return redirect(url_for("reports"))
    return render_template("report_detail.html", record=record)


@app.get("/reports/<int:record_id>/file")
def download_report_file(record_id):
    init_database()
    with get_connection() as connection:
        record = connection.execute(
            "SELECT source_filename, source_mime_type, source_pdf FROM reports WHERE id = ?", (record_id,)
        ).fetchone()
    if not record or not record["source_pdf"]:
        return redirect(url_for("edit_report", record_id=record_id))
    return send_file(
        io.BytesIO(record["source_pdf"]),
        mimetype=record["source_mime_type"] or "application/pdf",
        as_attachment=True,
        download_name=record["source_filename"] or "report.pdf",
    )


@app.route("/reports/<int:record_id>/edit", methods=["GET", "POST"])
def edit_report(record_id):
    init_database()
    with get_connection() as connection:
        existing = connection.execute("SELECT * FROM reports WHERE id = ?", (record_id,)).fetchone()
    if not existing:
        return redirect(url_for("reports"))
    if request.method == "POST":
        record = {field: request.form.get(field, "") for field in REPORT_FIELDS}
        try:
            normalized = {field: str(record[field]).strip() for field in REPORT_FIELDS}
            availability = float(normalized["application_availability"].replace("%", "").replace(",", "."))
            tickets = int(normalized["identity_tickets"])
            incidents = int(normalized["total_incidents"])
            sla = float(normalized["sla_compliance"].replace("%", "").replace(",", "."))
            if not 0 <= availability <= 100 or not 0 <= sla <= 100 or tickets < 0 or incidents < 0:
                raise ValueError
            source_filename = existing["source_filename"]
            source_mime_type = existing["source_mime_type"]
            source_pdf = existing["source_pdf"]
            uploaded_file = request.files.get("source_file")
            if not source_pdf and uploaded_file and uploaded_file.filename:
                if not uploaded_file.filename.lower().endswith(".pdf"):
                    raise ValueError
                source_filename = secure_filename(uploaded_file.filename)
                source_mime_type = "application/pdf"
                source_pdf = uploaded_file.read()
            with get_connection() as connection:
                connection.execute(
                    """UPDATE reports SET report_period=?, department=?, report_id=?, report_date=?, generated_time=?,
                       report_status=?, primary_application=?, supporting_server=?, supporting_system=?, reporting_cycle=?,
                       application_availability=?, total_incidents=?, identity_tickets=?, sla_compliance=?,
                       source_filename=?, source_mime_type=?, source_pdf=? WHERE id=?""",
                    tuple(normalized[field] for field in REPORT_FIELDS[:10])
                    + (availability, incidents, tickets, sla, source_filename, source_mime_type, source_pdf, record_id),
                )
            return redirect(url_for("view_report", record_id=record_id))
        except (ValueError, sqlite3.IntegrityError):
            return render_template("report_edit.html", record=record, record_id=record_id, error="Periksa kembali field dan Report ID Anda."), 400
    return render_template("report_edit.html", record=existing, record_id=record_id, error=None)


@app.post("/reports/<int:record_id>/delete")
def delete_report(record_id):
    init_database()
    with get_connection() as connection:
        connection.execute("DELETE FROM reports WHERE id = ?", (record_id,))
    return redirect(url_for("reports"))


if __name__ == "__main__":
    init_database()
    app.run(debug=True)
