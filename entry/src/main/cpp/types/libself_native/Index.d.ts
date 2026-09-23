export interface NativeResult { json: string; bytes: ArrayBuffer; }
export const bind: (id: string, node: Object, callback: (event: string) => void) => void;
export const unbind: (id: string) => void;
export const request: (id: string, json: string, bytes?: ArrayBuffer) => Promise<NativeResult>;

export const camera: (json: string, rgba?: ArrayBuffer) => Promise<NativeResult>;
