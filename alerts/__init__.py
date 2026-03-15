# UpperCut — Alerts System (Phase 4)
from alerts.email_alerts import (
    pipeline_success,
    pipeline_failure,
    retry_exhausted,
    low_api_balance,
    quota_exceeded,
    daily_summary,
    intelligence_update,
)
