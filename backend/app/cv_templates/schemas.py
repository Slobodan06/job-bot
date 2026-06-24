from pydantic import BaseModel, Field


class CvTemplatePublic(BaseModel):
    key: str
    label: str
    description: str
    status: str = Field(description="available | yours | taken")
    accent_color: str = ""
    layout_family: str = ""


class SelectTemplateRequest(BaseModel):
    template_key: str = Field(min_length=1, max_length=64)


class SelectTemplateResponse(BaseModel):
    message: str
    template_key: str
    template_label: str
