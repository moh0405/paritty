from enum import StrEnum


class Role(StrEnum):
    DATA_MANAGER = "data_manager"
    MEDICAL_MONITOR = "medical_monitor"
    CENTRAL_MONITOR = "central_monitor"
    STUDY_LEAD = "study_lead"
    UNBLINDED_STATISTICIAN = "unblinded_statistician"
