export const PIPELINE_VERSION='self-linear-tint-v1';
export function srgbToLinear(v:number):number{return v<=.04045?v/12.92:Math.pow((v+.055)/1.055,2.4);}
export function linearToSrgb(v:number):number{return v<=.0031308?12.92*v:1.055*Math.pow(v,1/2.4)-.055;}
export const vertexShader=`varying vec2 vUv; void main(){vUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}`;
// Input texture is sRGB, decoded once by its GPU internal format (Three SRGBColorSpace).
// Masks are linear data, nearest sampled. Output conversion is Three's colorspace_fragment, once.
export const fragmentShader=`
uniform sampler2D baseMap;
uniform sampler2D masks[2];
uniform vec3 colors[8];
uniform float strengths[8];
uniform int count;
uniform sampler2D protection;
uniform int protectedSnapshot;
uniform sampler2D anchorMasks[2];
uniform vec3 anchorColors[8];
uniform float anchorStrengths[8];
uniform int anchorCount;
uniform bool original;
varying vec2 vUv;
void main(){
 vec4 base=texture2D(baseMap,vUv); vec3 result=base.rgb;vec3 anchor=base.rgb;
 float luminance=dot(base.rgb,vec3(0.2126,0.7152,0.0722));
 #pragma unroll_loop_start
 for(int i=0;i<8;i++){
  if(UNROLLED_LOOP_INDEX<count){
   float a=texture2D(masks[UNROLLED_LOOP_INDEX / 4],vUv)[UNROLLED_LOOP_INDEX % 4]*strengths[i];
   vec3 tint=colors[i]*clamp(luminance/0.35,0.0,1.5);
   result=mix(result,tint,a);
  }
  if(UNROLLED_LOOP_INDEX<anchorCount){
    float aa=texture2D(anchorMasks[UNROLLED_LOOP_INDEX / 4],vUv)[UNROLLED_LOOP_INDEX % 4]*anchorStrengths[i];
    anchor=mix(anchor,anchorColors[i]*clamp(luminance/0.35,0.0,1.5),aa);
  }
 }
 #pragma unroll_loop_end
 if(texture2D(protection,vUv).r>0.0)result=anchor;
 if(original)result=base.rgb;
 gl_FragColor=vec4(result,base.a);
 #include <colorspace_fragment>
}`;
