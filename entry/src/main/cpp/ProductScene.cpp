#include "ProductScene.h"
#include <chrono>
#include <cmath>
#include <algorithm>
#include <stdexcept>
#include <array>
namespace self {
namespace {
double seconds(){return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();}
GLuint compile(GLenum type,const char* source){
 GLuint id=glCreateShader(type);glShaderSource(id,1,&source,nullptr);glCompileShader(id);GLint ok=0;glGetShaderiv(id,GL_COMPILE_STATUS,&ok);
 if(!ok){char log[2048];glGetShaderInfoLog(id,sizeof(log),nullptr,log);glDeleteShader(id);throw std::runtime_error(log);}return id;
}
const char* vertex=R"(#version 300 es
layout(location=0) in vec3 position;layout(location=1) in vec3 normal;layout(location=2) in vec2 texcoord;
uniform mat4 projection;uniform mat3 rotation;uniform float lift;uniform float twist;uniform float centerY;uniform float cameraDistance;
out vec3 world;out vec3 n;out vec2 uv;
void main(){float c=cos(twist),s=sin(twist);mat3 spin=mat3(c,0.,-s,0.,1.,0.,s,0.,c);
world=rotation*(spin*position+vec3(lift*.09,lift-centerY,0.));n=rotation*spin*normal;uv=texcoord;
gl_Position=projection*vec4(world+vec3(0.,0.,-cameraDistance),1.);})";
const char* fragment=R"(#version 300 es
precision highp float;in vec3 world;in vec3 n;in vec2 uv;
uniform sampler2D paint;uniform float metallic;uniform float roughness;uniform float cameraDistance;out vec4 color;
const float PI=3.14159265;
vec3 srgb(vec3 c){return mix(c*12.92,1.055*pow(max(c,vec3(0.)),vec3(1./2.4))-.055,step(vec3(.0031308),c));}
vec3 light(vec3 N,vec3 V,vec3 L,vec3 radiance,vec3 base){
 vec3 H=normalize(V+L);float nv=max(dot(N,V),.001),nl=max(dot(N,L),0.),nh=max(dot(N,H),0.);
 float a=roughness*roughness,a2=a*a,d=a2/(PI*pow(nh*nh*(a2-1.)+1.,2.));
 float k=pow(roughness+1.,2.)/8.;float g=nv/(nv*(1.-k)+k)*nl/(nl*(1.-k)+k);
 vec3 f0=mix(vec3(.045),base,metallic);vec3 f=f0+(1.-f0)*pow(1.-max(dot(H,V),0.),5.);
 return ((1.-f)*(1.-metallic)*base/PI+d*g*f/(4.*nv*max(nl,.001)))*radiance*nl;
}
void main(){
 vec3 encoded=texture(paint,uv).rgb;
 vec3 N=normalize(n),V=normalize(vec3(0.,0.,cameraDistance)-world);
 vec3 base=mix(encoded/12.92,pow((encoded+.055)/1.055,vec3(2.4)),step(vec3(.04045),encoded));
 if(!gl_FrontFacing)N=-N;
 vec3 c=base*(.20+.09*max(N.y,0.))*(1.-metallic*.72);
 c+=light(N,V,normalize(vec3(-3.,4.,5.)),vec3(3.7,3.5,3.3),base);
 c+=light(N,V,normalize(vec3(4.,1.,3.)),vec3(1.7,1.9,2.2),base);
 c+=light(N,V,normalize(vec3(-1.,2.,-4.)),vec3(2.6,2.3,2.),base);
 // Broad studio reflection strips: only light, no scene props or photo backdrop.
 vec3 R=reflect(-V,N);float strip=pow(max(0.,1.-abs(R.x+.38)/.09),2.)*smoothstep(-.9,.2,R.y);
 float soft=pow(max(0.,1.-abs(R.x-.66)/.22),2.);
 c+=(strip*.40+soft*.12)*mix(vec3(.9),base,metallic*.7);
 c=c/(c+vec3(.72));color=vec4(srgb(c),1.);
})";
}
void ProductScene::load(const Asset& asset,bool lid){
 if(!program_){auto v=compile(GL_VERTEX_SHADER,vertex),f=compile(GL_FRAGMENT_SHADER,fragment);program_=glCreateProgram();glAttachShader(program_,v);glAttachShader(program_,f);glLinkProgram(program_);glDeleteShader(v);glDeleteShader(f);GLint ok=0;glGetProgramiv(program_,GL_LINK_STATUS,&ok);if(!ok)throw std::runtime_error("Product scene link failed");}
 if(!sampler_){glGenSamplers(1,&sampler_);glSamplerParameteri(sampler_,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glSamplerParameteri(sampler_,GL_TEXTURE_MAG_FILTER,GL_LINEAR);glSamplerParameteri(sampler_,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glSamplerParameteri(sampler_,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);}
 auto& part=parts_[lid?1:0];
 if(!lid){minY_=1e6;maxY_=-1e6;radius_=0;}
 for(const auto& v:asset.vertices){minY_=std::min(minY_,v.y);maxY_=std::max(maxY_,v.y);radius_=std::max(radius_,std::hypot(v.x,v.z));}
 if(!part.vao){glGenVertexArrays(1,&part.vao);glGenBuffers(1,&part.vbo);glGenBuffers(1,&part.ibo);}
 // Each part owns one immutable mip level; replacing a product replaces storage.
 glDeleteTextures(1,&part.texture);glGenTextures(1,&part.texture);
 glBindVertexArray(part.vao);glBindBuffer(GL_ARRAY_BUFFER,part.vbo);glBufferData(GL_ARRAY_BUFFER,asset.vertices.size()*sizeof(Vertex),asset.vertices.data(),GL_STATIC_DRAW);
 glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,sizeof(Vertex),nullptr);glEnableVertexAttribArray(0);
 glVertexAttribPointer(1,3,GL_FLOAT,GL_FALSE,sizeof(Vertex),reinterpret_cast<void*>(3*sizeof(float)));glEnableVertexAttribArray(1);
 glVertexAttribPointer(2,2,GL_FLOAT,GL_FALSE,sizeof(Vertex),reinterpret_cast<void*>(6*sizeof(float)));glEnableVertexAttribArray(2);
 glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,part.ibo);glBufferData(GL_ELEMENT_ARRAY_BUFFER,asset.indices.size()*sizeof(uint32_t),asset.indices.data(),GL_STATIC_DRAW);part.count=asset.indices.size();
 glActiveTexture(GL_TEXTURE0);glBindTexture(GL_TEXTURE_2D,part.texture);glPixelStorei(GL_UNPACK_ALIGNMENT,1);
 glBindSampler(0,0);glPixelStorei(GL_UNPACK_ROW_LENGTH,0);glPixelStorei(GL_UNPACK_SKIP_ROWS,0);glPixelStorei(GL_UNPACK_SKIP_PIXELS,0);
 glTexStorage2D(GL_TEXTURE_2D,1,GL_RGBA8,asset.image.width,asset.image.height);
 glTexSubImage2D(GL_TEXTURE_2D,0,0,0,asset.image.width,asset.image.height,GL_RGBA,GL_UNSIGNED_BYTE,asset.image.rgba.data());
 glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_BASE_LEVEL,0);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAX_LEVEL,0);
 GLuint auditFbo=0;glGenFramebuffers(1,&auditFbo);glBindFramebuffer(GL_FRAMEBUFFER,auditFbo);glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,part.texture,0);
 bool complete=glCheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE;
 std::array<uint8_t,4> pixel{};if(complete)glReadPixels(0,0,1,1,GL_RGBA,GL_UNSIGNED_BYTE,pixel.data());glBindFramebuffer(GL_FRAMEBUFFER,0);glDeleteFramebuffers(1,&auditFbo);
 if(!complete||pixel[0]!=asset.image.rgba[0]||pixel[1]!=asset.image.rgba[1]||pixel[2]!=asset.image.rgba[2])throw std::runtime_error("Product texture upload differs from source");
 if(!lid){parts_[1].count=0;yaw_=0;pitch_=-.14f;progress_=target_=0;animating_=false;}
}
void ProductScene::clear(){for(auto& p:parts_){glDeleteVertexArrays(1,&p.vao);glDeleteBuffers(1,&p.vbo);glDeleteBuffers(1,&p.ibo);glDeleteTextures(1,&p.texture);p={};}glDeleteSamplers(1,&sampler_);sampler_=0;glDeleteProgram(program_);program_=0;animating_=false;}
void ProductScene::view(float yaw,float pitch){yaw_=yaw;pitch_=std::clamp(pitch,-.55f,.55f);}
void ProductScene::open(bool open,bool motion,int direction){from_=progress_;target_=open?1:0;started_=seconds();direction_=direction<0?-1:1;animating_=motion&&from_!=target_;if(!animating_)progress_=target_;}
void ProductScene::stop(){progress_=target_;animating_=false;}
void ProductScene::draw(int w,int h){
 if(animating_){float t=std::clamp(float((seconds()-started_)/.85),0.f,1.f);float ease=t*t*t*(t*(t*6.-15.)+10.);progress_=from_+(target_-from_)*ease;animationFrames_++;if(t>=1)animating_=false;}
 glViewport(0,0,w,h);glDisable(GL_SCISSOR_TEST);glDisable(GL_BLEND);glDisable(GL_CULL_FACE);glClearColor(.9765,.9686,.9804,1);glClearDepthf(1);glDepthMask(GL_TRUE);glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);glEnable(GL_DEPTH_TEST);glDepthFunc(GL_LEQUAL);
 if(!program_)return;glUseProgram(program_);
 float cy=std::cos(yaw_),sy=std::sin(yaw_),cx=std::cos(pitch_),sx=std::sin(pitch_);
 float rotation[]={cy,sy*sx,-sy*cx,0,cx,sx,sy,-cy*sx,cy*cx};
 float f=1/std::tan(32.f*3.14159265f/360),a=float(w)/h,near=.1f,far=40.f;
 float low=minY_-(direction_<0?progress_*1.25f:0),high=maxY_+(direction_>0?progress_*1.25f:0);
 float cameraDistance=std::max((high-low)*.5f*f/.76f,radius_*f/a/.76f);
 glUniform1f(glGetUniformLocation(program_,"cameraDistance"),cameraDistance);glUniform1f(glGetUniformLocation(program_,"centerY"),(high+low)*.5f);
 float projection[]={f/a,0,0,0,0,f,0,0,0,0,(far+near)/(near-far),-1,0,0,2*far*near/(near-far),0};
 glUniformMatrix4fv(glGetUniformLocation(program_,"projection"),1,GL_FALSE,projection);glUniformMatrix3fv(glGetUniformLocation(program_,"rotation"),1,GL_FALSE,rotation);glUniform1i(glGetUniformLocation(program_,"paint"),7);glBindSampler(7,sampler_);
 for(int i=0;i<2;i++){auto& p=parts_[i];if(!p.count)continue;
  glUniform1f(glGetUniformLocation(program_,"lift"),i?progress_*1.25f*direction_:0);glUniform1f(glGetUniformLocation(program_,"twist"),i?progress_*1.4f:0);
  glUniform1f(glGetUniformLocation(program_,"metallic"),i?.82f:.06f);glUniform1f(glGetUniformLocation(program_,"roughness"),i?.23f:.28f);
  glActiveTexture(GL_TEXTURE7);glBindTexture(GL_TEXTURE_2D,p.texture);glBindVertexArray(p.vao);glDrawElements(GL_TRIANGLES,p.count,GL_UNSIGNED_INT,nullptr);
 }
}
}
