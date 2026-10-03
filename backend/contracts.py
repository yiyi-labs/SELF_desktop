"""Only proposals cross this boundary. Authorization and pixels remain on the phone."""
from typing import Literal, Annotated
import re
from product_catalog import allowed_refs, requests_product_effect, lookup
from care_catalog import allowed_care_ids, care_reason, care_usage, care_options, care_intent, products_declined, care_feedback
from pydantic import BaseModel, ConfigDict, Field

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


def catalog_language(language: str) -> str:
    """Reviewed catalog wording exists in zh/en; ja/ko presentations read the English source."""
    return language if language in ("zh", "en") else "en"

class Region(StrictModel):
    regionId: str = Field(min_length=1, max_length=100)
    description: str = Field(max_length=160)
    semantic: Literal["manual", "confirmed-lips"] = "manual"

class Layer(StrictModel):
    layerId: str
    regionId: str
    presetId: str
    intensityLevel: Literal["none", "light", "medium", "strong"]

class DialogueTurn(StrictModel):
    userText: str = Field(max_length=2000)
    reply: str = Field(max_length=400)
    choices: list[Annotated[str, Field(min_length=1,max_length=60)]] = Field(default_factory=list, max_length=3)
    productIds: list[str] = Field(default_factory=list, max_length=3)

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
    productContextIds: list[str] = Field(default_factory=list, max_length=3)
    dialogue: list[DialogueTurn] = Field(default_factory=list, max_length=3)
    resolvedChoice: str = Field(default="", max_length=60)
    responseLanguage: Literal["zh", "en", "ja", "ko"] = "zh"
    careAdviceRequested: bool = False
    dismissedProducts: bool = False
    regions: list[Region] = Field(max_length=32)
    layers: list[Layer] = Field(max_length=8)
    protectedRegionIds: list[str] = Field(max_length=32)
    uploadAuthorized: Literal[True]
    imageWidth: int = Field(default=768, ge=8, le=2048)
    imageHeight: int = Field(default=1024, ge=8, le=2048)
    annotatedRegionId: str = Field(default="", max_length=100)
    annotatedRegionIds: list[str] = Field(default_factory=list, max_length=4)

class Operation(StrictModel):
    operation: Literal["set_digital_tint", "set_effect_level", "remove_effect"]
    regionId: str
    presetId: Literal["rose", "terracotta"]
    intensityLevel: Literal["none", "light", "medium", "strong"]
    layerId: str = Field(default="", description="For set_digital_tint this MUST be empty: a new layer has no existing ID. For set_effect_level/remove_effect use the existing target layerId.")
    productProfileId: Literal[""] = Field(default="", description="Must be empty. No calibrated product profiles are registered.")

class CareGuide(StrictModel):
    productId: str = Field(min_length=5, max_length=12)
    whyHere: str = Field(min_length=8, max_length=100)
    howToUse: str = Field(min_length=8, max_length=140)

class SelectionObservation(StrictModel):
    regionId: str = Field(min_length=1, max_length=100)
    area: Literal['eye', 'cheek', 'forehead', 'nose', 'chin', 'lips', 'brow', 'face', 'body', 'unknown']
    concern: Literal['none', 'blemish', 'dryness', 'texture', 'unknown'] = 'none'
    confidence: Literal['clear', 'uncertain']
    basis: Literal['image', 'user']

class Plan(StrictModel):
    decision: Literal["edit", "explain", "clarify", "support"]
    shortMessage: str = Field(min_length=1, max_length=140)
    operations: list[Operation] = Field(max_length=4)
    explanationRefs: list[str] = Field(max_length=3, description="Only productId from supplied productInformation. Information only, not evidence of a calibrated effect. Without productInformation use [].")
    careGuide: CareGuide | None = Field(default=None, description="An independent OLAY care suggestion from careOptions; never a claim that a product reproduces a digital edit.")
    question: str = Field(max_length=200, description="Must be empty for edit/explain/support. Only decision=clarify may contain a question; a clarify plan must have operations=[]. Authorization confirmation is handled by the app, not this field.")
    choices: list[str] = Field(default_factory=list, max_length=3, description="Only for clarify: 2 or 3 short choices in responseLanguage answering ONE question, no numeric prefixes. Otherwise []. Never ask to choose a region when annotatedRegionId is already supplied.")
    selectionObservations: list[SelectionObservation] = Field(default_factory=list, max_length=4,
        description='Identify each numbered selection using the current clean/annotated images or explicit user text. Areas are visible anatomy, blemish is only a possible visible bump, never a diagnosis. If unclear use area=unknown, confidence=uncertain. Never infer health or skin type.')

PRESETS = {"rose": {"displayName": "柔玫瑰", "color": [0.66, 0.12, 0.30]}, "terracotta": {"displayName": "暖陶棕", "color": [0.65, 0.25, 0.18]}}
EN_PRESETS = {"rose":"Muted pink", "terracotta":"Warm clay"}
LEVELS = {"none": 0.0, "light": 0.18, "medium": 0.32, "strong": 0.5}

def listening_only(text: str) -> bool:
    # Explicit discussion / no-transformation intent. This narrows capabilities,
    # never manufactures an edit or a psychological diagnosis.
    return bool(re.search(r'只想聊聊|不用修改|先不要.*编辑|不想.{0,12}(?:改成|变成).{0,8}别人|just (?:want to )?talk|no edits|do not (?:edit|change)|don.t (?:edit|change)',text,re.I))

def validate_plan(plan: Plan, snapshot: Snapshot) -> Plan:
    if listening_only(snapshot.userText) and plan.decision=='edit':
        raise ValueError('conversation_only')
    if (plan.decision == 'support' and snapshot.careAdviceRequested and care_intent(snapshot.userText)
            and not listening_only(snapshot.userText) and not plan.operations):
        plan.decision = 'explain'
    # Display labels are a deterministic presentation mapping, never an edit rewrite.
    def display(text):
        for key, preset in PRESETS.items():
            text = re.sub(r"\b"+key+r"\b", (preset["displayName"] if snapshot.responseLanguage=="zh" else EN_PRESETS[key]), text, flags=re.I)
        if re.search(r"regionId|presetId|layerId|set_digital_tint|region-[\w-]+", text):
            raise ValueError("internal_identifier_in_reply")
        return text
    plan.shortMessage = display(plan.shortMessage)
    plan.question = display(plan.question)
    if plan.decision != 'clarify' and re.search(r'[？?]', plan.shortMessage):
        raise ValueError('question_outside_clarification')
    if snapshot.careAdviceRequested and care_intent(snapshot.userText) and re.search(
            r'米粒|豌豆|黄豆|\d+\s*(?:滴|泵|克|毫升|ml|g)|每日|每天|早晚各|rice.grain|pea.sized', plan.shortMessage, re.I):
        raise ValueError('unsupported_care_amount')
    if (care_intent(snapshot.userText) and not re.search(r'试色|颜色|柔玫瑰|暖陶棕|tint|colou?r', snapshot.userText, re.I)
            and re.search(r'透一点颜色|轻轻晕开|数字试色|数字上色|边缘轻轻散开', plan.shortMessage)):
        raise ValueError('care_replaced_by_tint')
    if products_declined(snapshot.userText) and re.search(r'(?:可以|不妨|建议|想再).{0,15}(?:看看|考虑|选|试|用).{0,8}(?:眼霜|面霜|olay|玉兰油|产品)', plan.shortMessage, re.I):
        raise ValueError('declined_product_pitch')
    selected = snapshot.annotatedRegionIds or ([snapshot.annotatedRegionId] if snapshot.annotatedRegionId else [])
    observations = plan.selectionObservations
    if len({o.regionId for o in observations}) != len(observations) or any(o.regionId not in selected for o in observations):
        raise ValueError('unselected_observation')
    if any(o.confidence == 'uncertain' and o.area != 'unknown' for o in observations):
        raise ValueError('uncertain_anatomy')
    clear = [o for o in observations if o.confidence == 'clear']
    areas = {o.area for o in clear}
    area = next(iter(areas)) if len(areas) == 1 else ''
    concern = 'blemish' if any(o.concern == 'blemish' for o in clear) else ''
    previous_products = snapshot.productContextIds + [i for turn in snapshot.dialogue for i in turn.productIds]
    explicit_product = bool(re.search(r'olay|玉兰油|产品|推荐|眼霜|面霜|精华|怎么用|用法|ingredients|recommend|product', snapshot.userText, re.I))
    declined = products_declined(snapshot.userText) or care_feedback(snapshot.userText) or (snapshot.dismissedProducts and not explicit_product)
    if observations and not clear:
        declined = True
    alternative = bool(re.search(r'换|其他|别款|推荐|哪款|alternative|recommend', snapshot.userText, re.I))
    newly_named = bool({p['productId'] for p in lookup(snapshot.userText, snapshot.productContextIds)} - set(previous_products))
    offer = not declined and (not previous_products or alternative or newly_named)
    if not offer:
        plan.careGuide = None
    # Care questions and concerns should still receive a source-linked routine
    # when no digital colour edit can honestly represent a product outcome.
    if (offer and snapshot.careAdviceRequested and care_intent(snapshot.userText) and
            not listening_only(snapshot.userText) and plan.decision in ('explain', 'clarify') and
            plan.careGuide is None):
        options = care_options(snapshot.userText, True, catalog_language(snapshot.responseLanguage), area, concern)
        if options:
            plan.careGuide = CareGuide(productId=options[0]['productId'],
                whyHere=care_reason(options[0]['productId'], catalog_language(snapshot.responseLanguage), snapshot.userText + (' 痘' if concern == 'blemish' else '')),
                howToUse=options[0]['ordinaryUse'])
    if plan.careGuide:
        if plan.decision == 'support' or not snapshot.careAdviceRequested or plan.careGuide.productId not in allowed_care_ids(snapshot.userText, True, area, concern):
            raise ValueError('unmatched_care_guide')
        # The model selects a matching identity in the same tool call. Wording
        # comes from reviewed category guidance: the listing does not support
        # invented makeup performance, quantities or efficacy claims.
        plan.careGuide.whyHere = care_reason(plan.careGuide.productId, catalog_language(snapshot.responseLanguage), snapshot.userText + (' 痘' if concern == 'blemish' else ''))
        plan.careGuide.howToUse = care_usage(snapshot.userText, True, plan.careGuide.productId, catalog_language(snapshot.responseLanguage))
        if plan.decision in ('explain', 'clarify') and re.search(r'做不到|不能.*(?:做|改)|工具.*(?:不行|不支持)', plan.shortMessage):
            plan.shortMessage = ('先把这处的日常护理放轻一些，下面是可以直接做的一步。'
                if snapshot.responseLanguage == 'zh' else 'Begin with a gentle routine for this area; the care card below gives one practical step.')
        if re.search(r'保证|必然|立刻|立即|永久|复刻|还原.*(?:试色|数字)|与.*(?:试色|数字).*相同',
                     plan.careGuide.whyHere + plan.careGuide.howToUse):
            raise ValueError('uncalibrated_care_claim')
    if listening_only(snapshot.userText) and re.search(r'我(?:会|已经)?记(?:着|住)|已(?:经)?(?:保存|保护)|以后(?:一直|都会)',plan.shortMessage):
        # No preference-write tool exists here. Keep the acknowledgement truthful;
        # this presentation fallback cannot create or authorize an operation.
        plan.shortMessage='这次先保留你现在的样子，我们慢慢聊。'
    if plan.decision=='clarify' and plan.question:
        # The dedicated question is rendered once beside the choices. Remove
        # duplicate question sentences from the acknowledgement, not the plan.
        statement=re.sub(r'[^。！？.!?]*[？?]','',plan.shortMessage).strip()
        if statement:
            plan.shortMessage=statement
    plan.choices = [display(choice) for choice in plan.choices]
    if plan.choices and (plan.decision != "clarify" or not plan.question or len(plan.choices)<2 or len(set(plan.choices))!=len(plan.choices) or any(not c.strip() or len(c)>60 for c in plan.choices)):
        raise ValueError("invalid_choices")
    if snapshot.resolvedChoice:
        if not snapshot.dialogue or snapshot.resolvedChoice not in snapshot.dialogue[-1].choices:
            raise ValueError("stale_choice")
    if re.fullmatch(r"[1-3]", snapshot.userText.strip()) and plan.decision == "edit":
        index = int(snapshot.userText.strip())-1
        if not snapshot.dialogue or index>=len(snapshot.dialogue[-1].choices) or snapshot.resolvedChoice!=snapshot.dialogue[-1].choices[index]:
            raise ValueError("ambiguous_numeric_reply")
    if plan.decision == 'edit' and (requests_product_effect(snapshot.userText,snapshot.productContextIds) or plan.explanationRefs):
        # There are currently zero experimentally calibrated product profiles.
        # Product facts/INCI cannot authorize a generic tint as a product result.
        raise ValueError('product_effect_not_calibrated')
    if plan.decision == 'edit' and re.search(r'痘|痘印|疤|acne|pimple|scar', snapshot.userText, re.I):
        raise ValueError('unsupported_skin_edit')
    if plan.decision != "edit" and plan.operations:
        raise ValueError("non-edit operation")
    if plan.decision == "edit" and not 1 <= len(plan.operations) <= 4:
        raise ValueError("one to four operations required")
    available_refs = allowed_refs(snapshot.userText,snapshot.productContextIds)
    if plan.careGuide:
        available_refs.add(plan.careGuide.productId)
    if set(plan.explanationRefs) - available_refs:
        raise ValueError("unregistered evidence")
    if plan.decision != "clarify" and plan.question:
        raise ValueError("unexpected question")
    regions = {r.regionId for r in snapshot.regions}
    layers = {r.layerId: r for r in snapshot.layers}
    selected = snapshot.annotatedRegionIds or ([snapshot.annotatedRegionId] if snapshot.annotatedRegionId else [])
    if len(selected) != len(set(selected)) or set(selected) - regions:
        raise ValueError("invalid selected regions")
    new_regions: set[str] = set()
    for op in plan.operations:
        selected_presets=[key for key,preset in PRESETS.items() if preset['displayName'] in snapshot.resolvedChoice or EN_PRESETS[key].lower() in snapshot.resolvedChoice.lower() or re.search(r'\b'+key+r'\b',snapshot.resolvedChoice,re.I)]
        if op.operation=='set_digital_tint' and len(selected_presets)==1 and op.presetId!=selected_presets[0]:
            raise ValueError('choice_preset_mismatch')
        if op.regionId not in regions:
            raise ValueError("unknown region")
        if op.operation == 'set_digital_tint' and selected and op.regionId not in selected:
            raise ValueError('selected_region_mismatch')
        if op.operation == 'set_digital_tint':
            if op.regionId in new_regions:
                raise ValueError('duplicate_region_operation')
            new_regions.add(op.regionId)
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
