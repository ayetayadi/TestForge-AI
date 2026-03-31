from sqlalchemy import Enum

OutcomeEnum = Enum(
    "approved",
    "reject_keep",
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