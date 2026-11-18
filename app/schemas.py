from pydantic import BaseModel, Field, field_validator

class CampaignCreate(BaseModel):
    name: str = Field(min_length=8, max_length=120)
    country: str = Field(min_length=2, max_length=2, pattern=r'^[A-Z]{2}$')
    offer_id: int = Field(gt=0)
    # Optional in the form, but the effective configuration MUST resolve all three.
    domain_id: int | None = Field(default=None, gt=0)
    group_id: int | None = Field(default=None, gt=0)
    traffic_source_id: int | None = Field(default=None, gt=0)

    @field_validator('name')
    @classmethod
    def safe_name(cls, value: str):
        import re
        if not re.fullmatch(r'test_[A-Za-z0-9_]+', value):
            raise ValueError('Name must use latin letters, digits and underscores, starting test_')
        return value

class DraftOfferChange(BaseModel):
    version: int = Field(ge=1)
    offer_id: int = Field(gt=0)


class DraftPinChange(DraftOfferChange):
    pinned: bool


class DraftVersion(BaseModel):
    version: int = Field(ge=1)
