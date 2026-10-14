from typing import Any, Optional
from pydantic import BaseModel, model_validator
class UpdateScheduleDTO(BaseModel):
    schedule_cron: Optional[str] = None
    lookback_days: Optional[int] = None
    run_on_startup: Optional[bool] = None

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_frontend_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        mapped = dict(data)
        if "pipeline_schedule_cron" in mapped and "schedule_cron" not in mapped:
            mapped["schedule_cron"] = mapped["pipeline_schedule_cron"]
        if "pipeline_lookback_days" in mapped and "lookback_days" not in mapped:
            mapped["lookback_days"] = mapped["pipeline_lookback_days"]
        if "pipeline_run_on_startup" in mapped and "run_on_startup" not in mapped:
            mapped["run_on_startup"] = mapped["pipeline_run_on_startup"]
        return mapped
