CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_period TEXT NOT NULL,
    department TEXT NOT NULL,
    report_id TEXT NOT NULL UNIQUE,
    report_date TEXT NOT NULL,
    generated_time TEXT NOT NULL,
    report_status TEXT NOT NULL,
    primary_application TEXT NOT NULL,
    supporting_server TEXT NOT NULL,
    supporting_system TEXT NOT NULL,
    reporting_cycle TEXT NOT NULL,
    application_availability REAL NOT NULL CHECK (application_availability >= 0 AND application_availability <= 100),
    total_incidents INTEGER NOT NULL CHECK (total_incidents >= 0),
    identity_tickets INTEGER NOT NULL CHECK (identity_tickets >= 0),
    sla_compliance REAL NOT NULL CHECK (sla_compliance >= 0 AND sla_compliance <= 100),
    source_filename TEXT,
    source_mime_type TEXT,
    source_pdf BLOB,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_reports_period ON reports(report_period);
CREATE INDEX IF NOT EXISTS idx_reports_application ON reports(primary_application);
