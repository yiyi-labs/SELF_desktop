"""Only proposals cross this boundary. Authorization and pixels remain on the phone."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

class Region(StrictModel):
    regionId: str = Field(min_length=1, max_length=100)
    description: str = Field(max_length=160)
    semantic: Literal["manual", "confirmed-lips"] = "manual"

class Layer(StrictModel):
    layerId: str
    regionId: str
    presetId: str
    intensityLevel: Literal["none", "light", "medium", "strong"]

class Snapshot(StrictModel):
    schemaVersion: Literal[1] = 1
    requestId: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    snapshotId: str = Field(min_length=1, max_length=100)
    assetId: str = Field(min_length=1, max_length=100)
    assetVersion: str = Field(min_length=1, max_length=100)
    textureVersion: str = Field(min_length=1, max_length=100)
    sceneRevision: int = Field(ge=0)
    regionVersion: int = Field(ge=0)
    viewRevision: int = Field(ge=0)
    view: dict[str, float] = Field(max_length=8)
    userText: str = Field(min_length=1, max_length=2000)
    regions: list[Region] = Field(max_length=32)
    layers: list[Layer] = Field(max_length=8)
    protectedRegionIds: list[str] = Field(max_length=32)
    uploadAuthorized: Literal[True]
    imageWidth: int = Field(default=768, ge=8, le=2048)
    imageHeight: int = Field(default=1024, ge=8, le=2048)
    annotatedRegionId: str = Field(default="", max_length=100)

class Operation(StrictModel):
    operation: Literal["set_digital_tint", "set_effect_level", "remove_effect"]
    regionId: str
    presetId: Literal["rose", "terracotta"]
    intensityLevel: Literal["none", "light", "medium", "strong"]
    layerId: str = Field(default="", description="For set_digital_tint this MUST be empty: a new layer has no existing ID. For set_effect_level/remove_effect use the existing target layerId.")
    productProfileId: Literal[""] = Field(default="", description="Must be empty. No calibrated product profiles are registered.")

class Plan(StrictModel):
    decision: Literal["edit", "explain", "clarify", "support"]
    shortMessage: str = Field(min_length=1, max_length=400)
    operations: list[Operation] = Field(max_length=1)
    explanationRefs: list[str] = Field(max_length=0, description="Must be []. No source evidence is registered. Region IDs, preset IDs and layer IDs are NOT evidence references.")
    question: str = Field(max_length=200, description="Must be empty for edit/explain/support. Only decision=clarify may contain a question; a clarify plan must have operations=[]. Authorization confirmation is handled by the app, not this field.")

PRESETS = {"rose": {"color": [0.66, 0.12, 0.30]}, "terracotta": {"color": [0.65, 0.25, 0.18]}}
LEVELS = {"none": 0.0, "light": 0.18, "medium": 0.32, "strong": 0.5}

def validate_plan(plan: Plan, snapshot: Snapshot) -> Plan:
    if plan.decision != "edit" and plan.operations:
        raise ValueError("non-edit operation")
    if plan.decision == "edit" and len(plan.operations) != 1:
        raise ValueError("one operation required")
    if plan.explanationRefs:  # No calibrated SKU/evidence is currently registered for model actions.
        raise ValueError("unregistered evidence")
    if plan.decision != "clarify" and plan.question:
        raise ValueError("unexpected question")
    regions = {r.regionId for r in snapshot.regions}
    layers = {r.layerId: r for r in snapshot.layers}
    for op in plan.operations:
        if op.regionId not in regions:
            raise ValueError("unknown region")
        if op.productProfileId:
            raise ValueError("uncalibrated product")
        if op.operation == "set_digital_tint":
            if op.layerId or op.intensityLevel == "none":
                raise ValueError("invalid new layer")
        else:
            layer = layers.get(op.layerId)
            if not layer or layer.regionId != op.regionId or layer.presetId != op.presetId:
                raise ValueError("layer mismatch")
            if op.operation == "remove_effect" and op.intensityLevel != "none":
                raise ValueError("removal requires none")
    return plan

TOOL = {"type": "function", "function": {
    "name": "propose_edit_plan",
    "description": "Submit a candidate only. This does not authorize or execute an edit.",
    "parameters": Plan.model_json_schema(),
}}
