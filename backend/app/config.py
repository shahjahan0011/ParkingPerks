from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/parking_perks"

    # Genetec
    genetec_base_url: str = ""
    genetec_username: str = ""
    genetec_password: str = ""

    # T2 Iris
    t2_iris_base_url: str = ""
    t2_iris_api_key: str = ""

    # T2 Flex
    t2_flex_base_url: str = ""
    t2_flex_client_id: str = ""
    t2_flex_client_secret: str = ""

    # Email
    smtp_host: str = "smtp.mail.ubc.ca"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    email_from: str = "parking.perks@ubc.ca"
    email_from_name: str = "UBC Parking Services"

    # Application
    manager_code: str = "UBCO-PERKS-2025"
    min_visits: int = 10
    min_hours: float = 1.0
    num_winners: int = 1
    campus_timezone: str = "America/Vancouver"

    # Scheduler
    draw_day_of_month: int = 1
    draw_hour: int = 9
    draw_minute: int = 0

    # Stub mode — use local test-data files instead of live APIs
    use_stubs: bool = True
    stub_data_dir: str = "../test-data"

    excluded_permit_series: list[str] = ["BIKE"]


settings = Settings()
