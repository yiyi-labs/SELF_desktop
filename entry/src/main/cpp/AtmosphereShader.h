#pragma once
namespace self {
constexpr const char* atmosphereVertex=R"(#version 300 es
const vec2 p[3]=vec2[3](vec2(-1.,-1.),vec2(3.,-1.),vec2(-1.,3.));
void main(){gl_Position=vec4(p[gl_VertexID],.999,1.);})";
constexpr const char* atmosphereFragment=R"(#version 300 es
precision highp float;uniform vec2 resolution;uniform float phase;uniform int palette;
out vec4 color;
void main(){vec2 uv=gl_FragCoord.xy/resolution;vec3 cool=vec3(.929,.933,.972),warm=vec3(.980,.942,.907);
if(palette==1){cool=vec3(.973,.927,.922);warm=vec3(.988,.953,.892);}if(palette==2){cool=vec3(.900,.954,.963);warm=vec3(.941,.969,.946);}
vec3 c=mix(warm,cool,uv.y*.75+uv.x*.15);
vec2 p=uv-vec2(.45+.04*sin(phase*.15),.59);float halo=exp(-dot(p*vec2(1.3,1.),p*vec2(1.3,1.))*8.);
c=mix(c,vec3(1.),halo*.45);float lens=exp(-pow((length(p*vec2(1.1,.85))-.44)*34.,2.));c=mix(c,vec3(1.),lens*.12);
for(int i=0;i<18;i++){float f=float(i);vec2 point=vec2(fract(sin(f*78.233)*43758.5),fract(sin(f*31.73)*2153.3));point+=vec2(sin(phase*.12+f),cos(phase*.08+f*2.))*.018;float radius=.0015+fract(f*.37)*.002;float particle=1.-smoothstep(radius*.3,radius,length((uv-point)*vec2(resolution.x/resolution.y,1.)));c=mix(c,vec3(1.),particle*.55);}
color=vec4(c,1.);})";
}
