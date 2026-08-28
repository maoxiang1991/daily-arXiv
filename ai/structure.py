from pydantic import BaseModel, Field, field_validator
import re

class Structure(BaseModel):
    tldr: str = Field(description="generate a too long; didn't read summary")
    motivation: str = Field(description="describe the motivation in this paper")
    method: str = Field(description="method of this paper")
    result: str = Field(description="result of this paper")
    conclusion: str = Field(description="conclusion of this paper")
    abstract_zh: str = Field(description="a complete and faithful Chinese translation of the original paper abstract (translate the ENTIRE abstract into Chinese, keeping all technical details and terminology, no omissions)")
    groups: list[str] = Field(description="names of the topic groups this paper belongs to, chosen ONLY from the topic group list provided in the task; return an empty list if none applies")