"""Tools of the list agent, as seen by the LLM: a name, a description and typed arguments.

These classes are only the schemas sent to the model with bind_tools. The model can only ask
for a call; the code validates the arguments with the same schema and decides whether to run it.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class click(BaseModel):     # lower case: the class name is the tool name the model sees
    """Click one numbered element of the last observation: a pagination control (next page,
    page number, load more), or a cookie banner button. Never anything else."""
    model_config = ConfigDict(extra="forbid")

    element_id: int = Field(ge=1, description="Number of the element, as shown in the last observation")
    purpose: Literal["pagination", "cookie_refusal", "cookie_acceptance"] = Field(
        description="Why this element is clicked")
