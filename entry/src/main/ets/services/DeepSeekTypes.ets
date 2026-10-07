/** Wire types for the DeepSeek chat completions API. Transport-level only; business semantics stay in the clients. */
export interface DeepSeekTextPart {type:string;text:string;}
export interface DeepSeekImagePart {type:string;image_url:DeepSeekImageUrl;}
export interface DeepSeekImageUrl {url:string;}
export type DeepSeekContentPart=DeepSeekTextPart|DeepSeekImagePart;
export interface DeepSeekMessage {role:string;content:string|DeepSeekContentPart[];}
export interface DeepSeekToolChoice {type:string;function:DeepSeekToolChoiceFunction;}
export interface DeepSeekToolChoiceFunction {name:string;}
export interface DeepSeekRequestBody {
 model:string;thinking:DeepSeekThinking;stream:boolean;max_tokens:number;
 messages:DeepSeekMessage[];tools?:object[];tool_choice?:DeepSeekToolChoice;
}
export interface DeepSeekThinking {type:string;}
export interface DeepSeekToolCallFunction {name:string;arguments:string;}
export interface DeepSeekToolCall {id:string;type:string;function:DeepSeekToolCallFunction;}
export interface DeepSeekResponseMessage {role:string;content:string|null;tool_calls?:DeepSeekToolCall[];}
export interface DeepSeekChoice {index?:number;message:DeepSeekResponseMessage;finish_reason:string|null;}
export interface DeepSeekUsage {prompt_tokens?:number;completion_tokens?:number;total_tokens?:number;}
export interface DeepSeekRawResponse {
 id?:string;model?:string;system_fingerprint?:string|null;choices:DeepSeekChoice[];usage?:DeepSeekUsage;
}
/** Stream chunk shape (SSE data payloads). */
export interface DeepSeekDeltaToolCall {index?:number;id?:string;type?:string;function?:DeepSeekDeltaToolFunction;}
export interface DeepSeekDeltaToolFunction {name?:string;arguments?:string;}
export interface DeepSeekStreamDelta {content?:string;tool_calls?:DeepSeekDeltaToolCall[];}
export interface DeepSeekStreamChunk {choices:DeepSeekStreamChoice[];}
export interface DeepSeekStreamChoice {index?:number;delta?:DeepSeekStreamDelta;finish_reason?:string|null;}

export type DeepSeekErrorCategory=
 'missing_key'|'invalid_key'|'payment_required'|'invalid_request'|'rate_limited'|'server_unavailable'|
 'network'|'timeout'|'background'|'cancelled'|'invalid_response'|'invalid_plan'|'repeated_response'|
 'missing_selection_analysis'|'ungrounded_conversation'|'image_rejected'|'https_required';
/** Public error carries only a category and a user-safe message; never headers, keys or response bodies. */
export class DeepSeekError extends Error {
 readonly category:DeepSeekErrorCategory;
 constructor(category:DeepSeekErrorCategory,message:string){super(message);this.category=category;}
}
/** The propose_edit_plan tool parameter schema, equivalent to the pydantic Plan schema the Python backend sent. */
export const PLAN_TOOL_SCHEMA_JSON:string='{"type":"function","function":{"name":"propose_edit_plan","description":"Submit a candidate only. This does not authorize or execute an edit.","parameters":{"$defs":{"CareGuide":{"additionalProperties":false,"properties":{"productId":{"maxLength":12,"minLength":5,"title":"Productid","type":"string"},"whyHere":{"maxLength":100,"minLength":8,"title":"Whyhere","type":"string"},"howToUse":{"maxLength":140,"minLength":8,"title":"Howtouse","type":"string"}},"required":["productId","whyHere","howToUse"],"title":"CareGuide","type":"object"},"Operation":{"additionalProperties":false,"properties":{"operation":{"enum":["set_digital_tint","set_effect_level","remove_effect"],"title":"Operation","type":"string"},"regionId":{"title":"Regionid","type":"string"},"presetId":{"enum":["rose","terracotta"],"title":"Presetid","type":"string"},"intensityLevel":{"enum":["none","light","medium","strong"],"title":"Intensitylevel","type":"string"},"layerId":{"default":"","description":"For set_digital_tint this MUST be empty: a new layer has no existing ID. For set_effect_level/remove_effect use the existing target layerId.","title":"Layerid","type":"string"},"productProfileId":{"const":"","default":"","description":"Must be empty. No calibrated product profiles are registered.","title":"Productprofileid","type":"string"}},"required":["operation","regionId","presetId","intensityLevel"],"title":"Operation","type":"object"},"SelectionObservation":{"additionalProperties":false,"properties":{"regionId":{"maxLength":100,"minLength":1,"title":"Regionid","type":"string"},"area":{"enum":["eye","cheek","forehead","nose","chin","lips","brow","face","body","unknown"],"title":"Area","type":"string"},"concern":{"default":"none","enum":["none","blemish","dryness","texture","unknown"],"title":"Concern","type":"string"},"confidence":{"enum":["clear","uncertain"],"title":"Confidence","type":"string"},"basis":{"enum":["image","user"],"title":"Basis","type":"string"}},"required":["regionId","area","confidence","basis"],"title":"SelectionObservation","type":"object"}},"additionalProperties":false,"properties":{"decision":{"enum":["edit","explain","clarify","support"],"title":"Decision","type":"string"},"shortMessage":{"maxLength":140,"minLength":1,"title":"Shortmessage","type":"string"},"operations":{"items":{"$ref":"#/$defs/Operation"},"maxItems":4,"title":"Operations","type":"array"},"explanationRefs":{"description":"Only productId from supplied productInformation. Information only, not evidence of a calibrated effect. Without productInformation use [].","items":{"type":"string"},"maxItems":3,"title":"Explanationrefs","type":"array"},"careGuide":{"anyOf":[{"$ref":"#/$defs/CareGuide"},{"type":"null"}],"default":null,"description":"An independent OLAY care suggestion from careOptions; never a claim that a product reproduces a digital edit."},"question":{"description":"Must be empty for edit/explain/support. Only decision=clarify may contain a question; a clarify plan must have operations=[]. Authorization confirmation is handled by the app, not this field.","maxLength":200,"title":"Question","type":"string"},"choices":{"description":"Only for clarify: 2 or 3 short choices in responseLanguage answering ONE question, no numeric prefixes. Otherwise []. Never ask to choose a region when annotatedRegionId is already supplied.","items":{"type":"string"},"maxItems":3,"title":"Choices","type":"array"},"selectionObservations":{"description":"Identify each numbered selection using the current clean/annotated images or explicit user text. Areas are visible anatomy, blemish is only a possible visible bump, never a diagnosis. If unclear use area=unknown, confidence=uncertain. Never infer health or skin type.","items":{"$ref":"#/$defs/SelectionObservation"},"maxItems":4,"title":"Selectionobservations","type":"array"}},"required":["decision","shortMessage","operations","explanationRefs","question"],"title":"Plan","type":"object"}}}';
