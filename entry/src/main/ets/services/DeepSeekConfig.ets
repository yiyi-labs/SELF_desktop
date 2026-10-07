/** DeepSeek official HTTPS API, centralised. Host/model live here only; never per page, never a key. */
export class DeepSeekConfig {
 static readonly BASE_URL:string='https://api.deepseek.com';
 static readonly MODEL:string='deepseek-flash';
 static readonly CONNECT_TIMEOUT_MS:number=10000;
 static readonly PLANNER_READ_TIMEOUT_MS:number=55000;
 static readonly STORY_READ_TIMEOUT_MS:number=45000;
 /** Same overall budget the Python backend enforced for its two-attempt planner loop. */
 static readonly PLANNER_BUDGET_MS:number=48000;
 static readonly STORY_BUDGET_MS:number=40000;
 static readonly MAX_TOOL_ARGUMENTS:number=16384;
 static readonly MAX_IMAGE_BYTES:number=5*1024*1024;
}
