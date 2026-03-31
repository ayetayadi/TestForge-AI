from pydantic import BaseModel, Field
from typing import List, Literal, Union, Annotated


class RunByProject(BaseModel):
    type: Literal["project"]
    project_id: str


class RunByKeys(BaseModel):
    type: Literal["keys"]
    issue_keys: List[str]


RunPipelineRequest = Annotated[
    Union[RunByProject, RunByKeys],
    Field(discriminator="type")
]