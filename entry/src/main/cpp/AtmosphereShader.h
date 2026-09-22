#pragma once
namespace self {
constexpr const char* atmosphereVertex=R"(#version 300 es
const vec2 p[3]=vec2[3](vec2(-1.,-1.),vec2(3.,-1.),vec2(-1.,3.));
void main(){gl_Position=vec4(p[gl_VertexID],.999,1.);})";
constexpr const char* atmosphereFragment=R"(#version 300 es
precision highp float;uniform vec2 resolution;uniform float phase;uniform int palette;
out vec4 color;
void main(){vec2 uv=gl_FragCoord.xy/resolution;float aspect=resolution.x/resolution.y;
vec3 cool=vec3(.63,.60,.80),warm=vec3(.95,.79,.68),mint=vec3(.61,.80,.80);
if(palette==1){cool=vec3(.78,.59,.73);warm=vec3(.99,.82,.61);mint=vec3(.83,.77,.87);}if(palette==2){cool=vec3(.54,.75,.80);warm=vec3(.84,.92,.80);mint=vec3(.68,.76,.91);}
vec3 c=mix(warm,cool,smoothstep(0.,1.,uv.y)*.82);
vec2 p=uv-vec2(.48+.025*sin(phase*.12),.57+.015*cos(phase*.1));
float halo=exp(-dot(p*vec2(1.25,1.),p*vec2(1.25,1.))*9.);
c=mix(c,vec3(.99,.96,.93),halo*.83);
float aurora=exp(-pow((uv.x+.10*sin(uv.y*5.+phase*.09)-.16)*3.2,2.));
c=mix(c,mint,aurora*.44*(1.-halo*.6));
float lens=exp(-pow((length(p*vec2(aspect*.65,1.))-.43)*19.,2.));c+=vec3(.055,.040,.070)*lens;
for(int i=0;i<26;i++){float f=float(i);vec2 point=vec2(fract(sin(f*78.233)*43758.5),fract(sin(f*31.73)*2153.3));point+=vec2(sin(phase*.11+f),cos(phase*.07+f*2.))*.022;float radius=.0017+fract(f*.37)*.003;float d=length((uv-point)*vec2(aspect,1.));float particle=exp(-pow(d/radius,2.));c=mix(c,vec3(1.,.97,.90),particle*.65);}
color=vec4(c,1.);})";
}
