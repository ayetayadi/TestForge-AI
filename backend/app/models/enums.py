from sqlalchemy import Enum

OutcomeEnum = Enum(
    "approved",
    "reject_keep",
    "no_improvement",
    "max_iter",
    "failed",
    name="us_outcome"
)

HumanChoiceEnum = Enum(
    "approve",
    "reject_keep",
    "reject_relaunch",
    name="us_human_choice"
)

SourceEnum = Enum(
    "jira",
    "ai",
    name="us_source"
)


StatusEnum = Enum(
    "queued",
    "processing",
    "completed",
    "failed",
    name="us_status"
)
