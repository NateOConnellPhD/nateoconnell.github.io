"""Frozen predictive specification, separate from every merit-ranking rule."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ForecastConfig:
    model: str = 'forecast-v7'
    margin_weight: float = .75
    drift_sd: float = 1.5
    prior_log_sd: float = .35
    prior_first_season: int = 2022
    first_forecast_season: int = 2023
    prior_max_week: int = 5
    fcs_ridge: float = 2.
    seed: int = 2026

    def identity(self):
        return asdict(self)

    @classmethod
    def from_legacy(cls, variant):
        if variant != 'V7LDe75':
            raise ValueError('Only the frozen V7LDe75 forecast specification is supported')
        return cls()


CONFIG = ForecastConfig()
