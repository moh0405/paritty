"""Site personalities (spec §7.2). Only ever stored in answer_key.site_personality; app code must not read it."""
from dataclasses import dataclass
from enum import StrEnum


class Personality(StrEnum):
    NORMAL = "normal"
    UNDER_REPORTER = "under_reporter"
    SLOPPY_ENTRY = "sloppy_entry"
    TOO_PERFECT = "too_perfect"
    RULE_BENDER = "rule_bender"
    SLOW_RESPONDER = "slow_responder"


@dataclass(frozen=True)
class PersonalityParams:
    entry_lag: tuple[int, int]          # days between event and EDC entry
    response_mean_days: float           # lognormal mean for query response
    wrong_correction_rate: float
    error_multiplier: float             # relative rate of planted edit-check errors


PARAMS: dict[Personality, PersonalityParams] = {
    Personality.NORMAL: PersonalityParams((1, 5), 5.0, 0.05, 1.0),
    Personality.UNDER_REPORTER: PersonalityParams((1, 5), 5.0, 0.05, 1.0),
    Personality.SLOPPY_ENTRY: PersonalityParams((10, 25), 5.0, 0.05, 3.0),
    Personality.TOO_PERFECT: PersonalityParams((1, 5), 5.0, 0.05, 1.0),
    Personality.RULE_BENDER: PersonalityParams((1, 5), 5.0, 0.05, 1.0),
    Personality.SLOW_RESPONDER: PersonalityParams((1, 5), 20.0, 0.20, 1.0),
}

NON_NORMAL = [p for p in Personality if p is not Personality.NORMAL]
