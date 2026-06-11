from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Genetec (plate reads) -- live client not yet implemented; use stub
    genetec_base_url: str = ""
    genetec_username: str = ""
    genetec_password: str = ""

    # T2 Iris (payments) -- SOAP TransactionInfoService
    # Auth: WS-Security UsernameToken (username+password) at transport level
    #       PLUS a TransactionInfo token as the method-level parameter.
    t2_iris_base_url: str = "https://iris.digitalpaytech.com/services"
    t2_iris_username: str = ""       # Iris portal login email
    t2_iris_password: str = ""       # Iris portal password
    t2_iris_token: str = ""          # TransactionInfo token from Iris API - Read section
    # 'version' method param. v1.2 is REQUIRED for plateNumber in responses
    # (v1.0/empty -> plateNumber is None; v1.5 -> unparseable schema).
    t2_iris_version: str = "v1.2"

    # T2 Flex -- SOAP web services (T2_Flex_Misc.asmx / ExecuteQuery method)
    t2_flex_ws_url: str = ""
    t2_flex_username: str = ""
    t2_flex_password: str = ""
    t2_flex_query_permits_uid: int = 0
    t2_flex_query_citations_uid: int = 0
    t2_flex_query_customer_uid: int = 4726  # customer lookup by PLATELICENSE
    t2_flex_verify_ssl: bool = True
    t2_flex_timeout: float = 60.0

    # Genetec Data Exporter ingest (OAuth2 client-credentials)
    # Generate long random values and mirror them in the exporter's
    # Authorization panel (Client ID / Client secret).
    ingest_client_id: str = ""
    ingest_client_secret: str = ""
    # Date format selected in the Data Exporter config ("Date format" dropdown)
    genetec_date_format: str = "MM/dd/yyyy"  # or yyyy-MM-dd / dd/MM/yyyy

    # Email -- backend: "gmail" (OAuth2 refresh token), "smtp", or "none"
    email_backend: str = "none"
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_refresh_token: str = ""
    gmail_sender: str = ""
    # Gmail search that finds the daily Genetec reads-report emails
    gmail_report_query: str = 'subject:"DailyReadsReport-ParkingPerks" has:attachment'
    # SMTP fallback (UBC Exchange)
    smtp_host: str = "smtp.mail.ubc.ca"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    email_from: str = "parking.perks@ubc.ca"
    email_from_name: str = "UBC Parking Services"

    # Monthly automated run
    report_recipients: str = "jeff.joyce@ubc.ca,jahan.shah@ubc.ca"
    min_coverage_days: int = 26   # reads must cover at least this many days of the month

    # Application
    manager_code: str = "UBCO-PERKS-2025"
    min_visits: int = 10
    min_hours: float = 1.0
    num_winners: int = 1
    campus_timezone: str = "America/Vancouver"

    # Stub flags (set to false individually as live APIs become available)
    # NOTE: plate reads have no stub flag -- they always come from the
    # manually exported Security Desk file (uploads/plate_reads.xlsx).
    use_stubs: bool = True          # T2 Flex: citations + permits
    use_stubs_payments: bool = True # T2 Iris: payments

    stub_data_dir: str = "../test-data"

    # Staff-uploaded plate reads land here; Genetec stub checks here first
    uploads_dir: str = "./uploads"

    excluded_permit_series: list[str] = ["BIKE"]


settings = Settings()
