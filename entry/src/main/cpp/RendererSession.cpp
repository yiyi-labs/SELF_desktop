#include "RendererSession.h"
#include "RegionSelection.h"
#include "EditCompositor.h"
#include "AtmosphereShader.h"
#include <hilog/log.h>
#include <chrono>
#include <cmath>
#include <algorithm>
#include <cstring>
#include <stdexcept>
namespace self {
static void check(bool result,const std::string& message){if(!result)throw std::runtime_error(message);}
static void eglCheck(bool ok,const char* step){if(!ok)throw std::runtime_error(std::string(step)+" EGL="+std::to_string(eglGetError()));}
static void glCheck(const char* step){auto e=glGetError();if(e!=GL_NO_ERROR)throw std::runtime_error(std::string(step)+" GL="+std::to_string(e));}
static GLuint shader(GLenum type,const char* source){GLuint s=glCreateShader(type);glShaderSource(s,1,&source,nullptr);glCompileShader(s);GLint status=0;glGetShaderiv(s,GL_COMPILE_STATUS,&status);if(!status){char log[4096];glGetShaderInfoLog(s,sizeof(log),nullptr,log);glDeleteShader(s);throw std::runtime_error(std::string("Shader: ")+log);}return s;}
static GLuint makeProgram(){
const char* vertex=R"(#version 300 es
layout(location=0) in vec3 position;layout(location=1) in vec2 texcoord;uniform mat4 mvp;out vec2 uv;
void main(){gl_Position=mvp*vec4(position,1.);uv=texcoord;})";
const char* fragment=R"(#version 300 es
precision highp float;precision highp sampler2DArray;
in vec2 uv;layout(location=0) out vec4 color;
uniform sampler2D base;uniform sampler2DArray masks;uniform sampler2D protectedMask;uniform sampler2D annotationMask;
uniform vec3 colors[16];uniform float strengths[16];uniform int exceptions[8];uniform int count;uniform int anchorCount;uniform bool original;uniform int auditMode;
vec3 linearRGB(vec3 c){return mix(c/12.92,pow((c+.055)/1.055,vec3(2.4)),step(vec3(.04045),c));}
vec3 srgb(vec3 c){return mix(c*12.92,1.055*pow(max(c,vec3(0.)),vec3(1./2.4))-.055,step(vec3(.0031308),c));}
vec3 composite(vec3 c,int first,int n){float luminance=dot(c,vec3(.2126,.7152,.0722));for(int i=0;i<8;i++){if(i>=n)break;float m=texture(masks,vec3(uv,float(first+i))).r;vec3 tint=linearRGB(colors[first+i]);c=mix(c,tint*clamp(luminance/.35,0.,1.5),m*strengths[first+i]);}return c;}
void main(){vec3 b=texture(base,uv).rgb;vec3 c=b;
if(auditMode==1){float cover=0.,exceptionCover=0.;for(int i=0;i<8;i++){if(i>=count)break;float m=texture(masks,vec3(uv,float(i))).r;cover=max(cover,m);if(exceptions[i]==1&&strengths[i]>0.)exceptionCover=max(exceptionCover,m);}color=vec4(cover>0.?1.:0.,texture(protectedMask,uv).r>0.&&exceptionCover==0.?1.:0.,0.,1.);return;}
if(auditMode==2){color=vec4(srgb(composite(b,8,anchorCount)),1.);return;}
if(!original){
 c=composite(b,0,count);
 if(texture(protectedMask,uv).r>0.){
  c=composite(b,8,anchorCount);
  float luminance=dot(c,vec3(.2126,.7152,.0722));
  for(int i=0;i<8;i++){
   if(i>=count)break;
   if(exceptions[i]==1)c=mix(c,linearRGB(colors[i])*clamp(luminance/.35,0.,1.5),texture(masks,vec3(uv,float(i))).r*strengths[i]);
  }
 }
}
if(auditMode==3&&texture(annotationMask,uv).r>0.)c=mix(c,linearRGB(vec3(.55,.25,.8)),.4);
color=vec4(srgb(c),1.);
})";
 auto v=shader(GL_VERTEX_SHADER,vertex),f=shader(GL_FRAGMENT_SHADER,fragment);GLuint p=glCreateProgram();glAttachShader(p,v);glAttachShader(p,f);glLinkProgram(p);glDeleteShader(v);glDeleteShader(f);GLint status=0;glGetProgramiv(p,GL_LINK_STATUS,&status);if(!status){char log[4096];glGetProgramInfoLog(p,sizeof(log),nullptr,log);glDeleteProgram(p);throw std::runtime_error(std::string("Link: ")+log);}return p;
}
RendererSession::RendererSession(){thread_=std::thread([this]{loop();});}
RendererSession::~RendererSession(){ {std::lock_guard<std::mutex> lock(mutex_);stopping_=true;}wake_.notify_one();thread_.join();}
std::future<Result> RendererSession::enqueue(std::function<Result()> fn){auto job=std::make_shared<Job>();job->run=std::move(fn);auto future=job->promise.get_future();{std::lock_guard<std::mutex> lock(mutex_);if(stopping_)throw std::runtime_error("Session closed");jobs_.push_back(job);}wake_.notify_one();return future;}
std::future<Result> RendererSession::submit(Json j,std::vector<uint8_t> b){return enqueue([this,j=std::move(j),b=std::move(b)]{return execute(j,b);});}
Result RendererSession::process(Json j,std::vector<uint8_t> bytes){
 auto type=j.at("type").get<std::string>();Result result;
 if(type=="LOAD"){
  auto next=j.value("kind","")=="glb"?loadGLB(bytes):photoAsset(bytes); // Decode/parse outside the GL worker.
  result=enqueue([this,next=std::move(next)]()mutable{check(surface_!=EGL_NO_SURFACE,"Native surface unavailable");asset_=std::move(next);masks_.clear();featherMasks_.clear();operations_=Json::array();anchors_=Json::array();protectId_.clear();protectRule_.clear();hasAsset_=true;if(asset_.photo)yaw_=pitch_=0;upload();dirty_=true;schedule();return Result{{{"width",asset_.image.width},{"height",asset_.image.height},{"vertices",asset_.vertices.size()},{"triangles",asset_.indices.size()/3}}};}).get();
 }else if(type=="NORMALIZE"){auto img=decodeImage(bytes);result.data={{"width",img.width},{"height",img.height}};result.images.push_back(std::move(img));}
 else result=submit(std::move(j),std::move(bytes)).get();
 // Native Image encoding runs on the N-API async worker after the GL readback finishes.
 for(size_t i=0;i<result.images.size();i++){auto png=encodePNG(result.images[i]);result.bytes.insert(result.bytes.end(),png.begin(),png.end());if(i==0&&type=="SNAPSHOT")result.data["split"]=result.bytes.size();}result.images.clear();return result;
}
void RendererSession::attach(OHNativeWindow* window){
 check(window,"Missing NativeWindow");check(OH_NativeWindow_NativeObjectReference(window)==0,"NativeWindow reference");
 enqueue([this,window]{try{clearGL();initialize(window);window_=window;generation_++;if(hasAsset_)upload();dirty_=true;schedule();if(event)event({{"type","READY"},{"generation",generation_},{"graphics",lastInfo_}});}catch(const std::exception& e){if(window_!=window)OH_NativeWindow_NativeObjectUnreference(window);clearGL();if(event)event({{"type","ERROR"},{"message",e.what()}});}return Result{};});
}
void RendererSession::silenceEvents(){enqueue([this]{event=nullptr;foreground_=false;return Result{};}).get();}
void RendererSession::detach(){enqueue([this]{generation_++;orbit_=false;clearGL();return Result{};}).get();}
void RendererSession::resize(int w,int h){enqueue([this,w,h]{width_=std::max(1,w);height_=std::max(1,h);dirty_=true;schedule();return Result{};});}
void RendererSession::vsyncCallback(long long,void* data){auto* self=static_cast<RendererSession*>(data);{std::lock_guard<std::mutex> lock(self->mutex_);self->scheduled_=false;self->tick_=true;}self->wake_.notify_one();}
void RendererSession::schedule(){if(!foreground_||surface_==EGL_NO_SURFACE)return;std::lock_guard<std::mutex> lock(mutex_);if(!scheduled_){scheduled_=true;auto e=OH_NativeVSync_RequestFrame(vsync_,vsyncCallback,this);if(e){scheduled_=false;throw std::runtime_error("VSync request "+std::to_string(e));}}}
void RendererSession::loop(){
 vsync_=OH_NativeVSync_Create("SELF",4);
 for(;;){std::shared_ptr<Job> job;bool frame=false;{std::unique_lock<std::mutex> lock(mutex_);wake_.wait(lock,[this]{return stopping_||!jobs_.empty()||tick_;});if(stopping_)break;if(!jobs_.empty()){job=jobs_.front();jobs_.pop_front();}else{frame=tick_;tick_=false;}}
  if(job){try{job->promise.set_value(job->run());}catch(...){job->promise.set_exception(std::current_exception());}}
  else if(frame&&foreground_&&surface_!=EGL_NO_SURFACE&&(dirty_||orbit_||motion_)){try{auto start=std::chrono::steady_clock::now();auto time=std::chrono::duration_cast<std::chrono::nanoseconds>(start.time_since_epoch()).count();if(!dirty_&&nextAnimatedDraw_&&time<nextAnimatedDraw_){schedule();continue;}if(!nextAnimatedDraw_||time-nextAnimatedDraw_>100000000)nextAnimatedDraw_=time;do{nextAnimatedDraw_+=33333333;}while(nextAnimatedDraw_<=time);float delta=lastAnimatedDraw_?std::min(.1f,float(time-lastAnimatedDraw_)/1e9f):0.f;lastAnimatedDraw_=time;if(motion_)phase_+=delta;if(orbit_){orbitPhase_+=.016;yaw_+=std::cos(orbitPhase_*.08)*.0004f;}draw();eglCheck(eglSwapBuffers(display_,surface_),"swap");dirty_=false;frameCount_++;if(lastPresented_&&(motion_||orbit_))frameIntervals_.push_back(double(time-lastPresented_)/1e6);lastPresented_=time;if(frameIntervals_.size()>24000)frameIntervals_.erase(frameIntervals_.begin(),frameIntervals_.begin()+12000);frameTimes_.push_back(std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count());if(frameTimes_.size()>24000)frameTimes_.erase(frameTimes_.begin(),frameTimes_.begin()+12000);if(orbit_||motion_)schedule();}catch(const std::exception& e){orbit_=false;if(event)event({{"type","ERROR"},{"message",e.what()}});}}
 }
 // No JS/UI waits occur on this thread. Destroy VSync before freeing callback data.
 OH_NativeVSync_Destroy(vsync_);vsync_=nullptr;clearGL();
 for(auto& job:jobs_)job->promise.set_exception(std::make_exception_ptr(std::runtime_error("Session closed")));
}
void RendererSession::initialize(OHNativeWindow* window){
 display_=eglGetDisplay(EGL_DEFAULT_DISPLAY);eglCheck(display_!=EGL_NO_DISPLAY,"get display");eglCheck(eglInitialize(display_,nullptr,nullptr),"initialize");
 const EGLint attributes[]={EGL_SURFACE_TYPE,EGL_WINDOW_BIT|EGL_PBUFFER_BIT,EGL_RENDERABLE_TYPE,EGL_OPENGL_ES3_BIT,EGL_RED_SIZE,8,EGL_GREEN_SIZE,8,EGL_BLUE_SIZE,8,EGL_ALPHA_SIZE,8,EGL_DEPTH_SIZE,24,EGL_NONE};
 EGLConfig config;EGLint count=0;eglCheck(eglChooseConfig(display_,attributes,&config,1,&count)&&count==1,"ES3 config");
 const EGLint ctx[]={EGL_CONTEXT_CLIENT_VERSION,3,EGL_NONE};context_=eglCreateContext(display_,config,EGL_NO_CONTEXT,ctx);eglCheck(context_!=EGL_NO_CONTEXT,"ES3 context");
 const EGLint attr[]={EGL_NONE};surface_=eglCreateWindowSurface(display_,config,reinterpret_cast<EGLNativeWindowType>(window),attr);eglCheck(surface_!=EGL_NO_SURFACE,"window surface");eglCheck(eglMakeCurrent(display_,surface_,surface_,context_),"make current");
 eglQuerySurface(display_,surface_,EGL_WIDTH,&width_);eglQuerySurface(display_,surface_,EGL_HEIGHT,&height_);eglSwapInterval(display_,1);
 auto string=[](GLenum key){auto p=glGetString(key);return p?std::string(reinterpret_cast<const char*>(p)):"";};
 GLint units=0;glGetIntegerv(GL_MAX_TEXTURE_IMAGE_UNITS,&units);check(units>=3,"Texture unit budget");
 lastInfo_={{"vendor",string(GL_VENDOR)},{"renderer",string(GL_RENDERER)},{"version",string(GL_VERSION)},{"glsl",string(GL_SHADING_LANGUAGE_VERSION)},{"textureUnits",units},{"abi",sizeof(void*)==8?"64-bit":"32-bit"},{"thread",std::hash<std::thread::id>{}(std::this_thread::get_id())}};
 OH_LOG_Print(LOG_APP,LOG_INFO,0xD003900,"SELF_NATIVE","GRAPHICS %{public}s",lastInfo_.dump().c_str());
 program_=makeProgram();{auto v=shader(GL_VERTEX_SHADER,atmosphereVertex),f=shader(GL_FRAGMENT_SHADER,atmosphereFragment);backgroundProgram_=glCreateProgram();glAttachShader(backgroundProgram_,v);glAttachShader(backgroundProgram_,f);glLinkProgram(backgroundProgram_);glDeleteShader(v);glDeleteShader(f);GLint status=0;glGetProgramiv(backgroundProgram_,GL_LINK_STATUS,&status);check(status,"Background link failed");}glGenVertexArrays(1,&vao_);glGenBuffers(1,&vbo_);glGenBuffers(1,&ebo_);glGenTextures(1,&texture_);glGenTextures(1,&maskArray_);glGenTextures(1,&protection_);glGenTextures(1,&annotation_);glCheck("initialize");
}
void RendererSession::clearGL(){if(display_!=EGL_NO_DISPLAY){if(context_!=EGL_NO_CONTEXT){glDeleteProgram(program_);glDeleteProgram(backgroundProgram_);glDeleteBuffers(1,&vbo_);glDeleteBuffers(1,&ebo_);glDeleteVertexArrays(1,&vao_);glDeleteTextures(1,&texture_);glDeleteTextures(1,&maskArray_);glDeleteTextures(1,&protection_);glDeleteTextures(1,&annotation_);eglMakeCurrent(display_,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT);}if(surface_!=EGL_NO_SURFACE)eglDestroySurface(display_,surface_);if(context_!=EGL_NO_CONTEXT)eglDestroyContext(display_,context_);eglTerminate(display_);}display_=EGL_NO_DISPLAY;context_=EGL_NO_CONTEXT;surface_=EGL_NO_SURFACE;program_=backgroundProgram_=vao_=vbo_=ebo_=texture_=maskArray_=protection_=annotation_=0;if(window_){OH_NativeWindow_NativeObjectUnreference(window_);window_=nullptr;}}
static void filtering(GLenum target,GLint filter){glTexParameteri(target,GL_TEXTURE_MIN_FILTER,filter);glTexParameteri(target,GL_TEXTURE_MAG_FILTER,filter);glTexParameteri(target,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glTexParameteri(target,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);}
void RendererSession::upload(){
 uploadedMasks_.fill("");uploadedProtection_="__uninitialized";
 glBindVertexArray(vao_);glBindBuffer(GL_ARRAY_BUFFER,vbo_);glBufferData(GL_ARRAY_BUFFER,asset_.vertices.size()*sizeof(Vertex),asset_.vertices.data(),GL_STATIC_DRAW);glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,sizeof(Vertex),nullptr);glEnableVertexAttribArray(0);glVertexAttribPointer(1,2,GL_FLOAT,GL_FALSE,sizeof(Vertex),reinterpret_cast<void*>(6*sizeof(float)));glEnableVertexAttribArray(1);glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,ebo_);glBufferData(GL_ELEMENT_ARRAY_BUFFER,asset_.indices.size()*sizeof(uint32_t),asset_.indices.data(),GL_STATIC_DRAW);
 glPixelStorei(GL_UNPACK_ALIGNMENT,1);glActiveTexture(GL_TEXTURE0);glBindTexture(GL_TEXTURE_2D,texture_);filtering(GL_TEXTURE_2D,GL_LINEAR);glTexImage2D(GL_TEXTURE_2D,0,GL_SRGB8_ALPHA8,asset_.image.width,asset_.image.height,0,GL_RGBA,GL_UNSIGNED_BYTE,asset_.image.rgba.data());
 glActiveTexture(GL_TEXTURE1);glBindTexture(GL_TEXTURE_2D_ARRAY,maskArray_);filtering(GL_TEXTURE_2D_ARRAY,GL_NEAREST);glTexImage3D(GL_TEXTURE_2D_ARRAY,0,GL_R8,asset_.image.width,asset_.image.height,16,0,GL_RED,GL_UNSIGNED_BYTE,nullptr);
 prepare({{"operations",operations_},{"anchorOperations",anchors_},{"protectionId",protectId_},{"protectionRuleId",protectRule_}});glCheck("asset upload");
}
std::array<float,16> RendererSession::matrix(int w,int h) const{
 float cy=std::cos(yaw_),sy=std::sin(yaw_),cx=std::cos(pitch_),sx=std::sin(pitch_);float a=float(w)/h,f=1/std::tan(35.f*3.1415926535f/360),n=.1f,z=100;
 std::array<float,16> m{cy,sy*sx,-sy*cx,0,0,cx,sx,0,sy,-cy*sx,cy*cx,0,panX_,panY_,-distance_,1};
 std::array<float,16> p{f/a,0,0,0,0,f,0,0,0,0,(z+n)/(n-z),-1,0,0,2*z*n/(n-z),0},r{};
 for(int col=0;col<4;col++)for(int row=0;row<4;row++)for(int k=0;k<4;k++)r[col*4+row]+=p[k*4+row]*m[col*4+k];return r;
}
void RendererSession::draw(bool original,int w,int h){
 if(!w)w=width_;if(!h)h=height_;glViewport(0,0,w,h);glDisable(GL_SCISSOR_TEST);if(auditMode_==1)glClearColor(0,0,0,1);else glClearColor(.941f,.925f,.941f,1);glClearDepthf(1.0f);glDepthMask(GL_TRUE);glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
 if(auditMode_!=1){glDisable(GL_DEPTH_TEST);glUseProgram(backgroundProgram_);glUniform2f(glGetUniformLocation(backgroundProgram_,"resolution"),w,h);glUniform1f(glGetUniformLocation(backgroundProgram_,"phase"),phase_);glUniform1i(glGetUniformLocation(backgroundProgram_,"palette"),palette_);glBindVertexArray(vao_);glDrawArrays(GL_TRIANGLES,0,3);}
 if(!hasAsset_)return;
 glEnable(GL_DEPTH_TEST);glDepthFunc(GL_LEQUAL);glDisable(GL_BLEND);glDisable(GL_CULL_FACE);glUseProgram(program_);glUniform1i(glGetUniformLocation(program_,"auditMode"),auditMode_);auto m=matrix(w,h);glUniformMatrix4fv(glGetUniformLocation(program_,"mvp"),1,GL_FALSE,m.data());glUniform1i(glGetUniformLocation(program_,"base"),0);glUniform1i(glGetUniformLocation(program_,"masks"),1);glUniform1i(glGetUniformLocation(program_,"protectedMask"),2);glUniform1i(glGetUniformLocation(program_,"annotationMask"),3);glActiveTexture(GL_TEXTURE3);glBindTexture(GL_TEXTURE_2D,annotation_);
 glActiveTexture(GL_TEXTURE0);glBindTexture(GL_TEXTURE_2D,texture_);glActiveTexture(GL_TEXTURE1);glBindTexture(GL_TEXTURE_2D_ARRAY,maskArray_);glActiveTexture(GL_TEXTURE2);glBindTexture(GL_TEXTURE_2D,protection_);
 glUniform1i(glGetUniformLocation(program_,"count"),operations_.size());glUniform1i(glGetUniformLocation(program_,"anchorCount"),anchors_.size());float colors[48]={},strengths[16]={};
 for(int anchor=0;anchor<2;anchor++){const auto& ops=anchor?anchors_:operations_;for(size_t i=0;i<ops.size();i++){strengths[anchor*8+i]=ops[i]["absoluteStrength"].get<float>();for(int c=0;c<3;c++)colors[(anchor*8+i)*3+c]=ops[i]["color"][c].get<float>();}}
 GLint exceptions[8]={};for(size_t i=0;i<operations_.size();i++)exceptions[i]=!protectRule_.empty()&&operations_[i].value("protectionException",std::string())==protectRule_;glUniform1iv(glGetUniformLocation(program_,"exceptions"),8,exceptions);
 glUniform3fv(glGetUniformLocation(program_,"colors"),16,colors);glUniform1fv(glGetUniformLocation(program_,"strengths"),16,strengths);glUniform1i(glGetUniformLocation(program_,"original"),original);glBindVertexArray(vao_);glDrawElements(GL_TRIANGLES,asset_.indices.size(),GL_UNSIGNED_INT,nullptr);
 if(!original&&tool_=="COMPARE"&&w==width_&&h==height_){glEnable(GL_SCISSOR_TEST);glScissor(0,0,w/2,h);glClear(GL_DEPTH_BUFFER_BIT);glUniform1i(glGetUniformLocation(program_,"original"),true);glDrawElements(GL_TRIANGLES,asset_.indices.size(),GL_UNSIGNED_INT,nullptr);glDisable(GL_SCISSOR_TEST);}glCheck("draw");
}
Image RendererSession::readFrame(int w,int h,bool original){
 check(w>0&&h>0&&w<=2048&&h<=2048,"Export size");GLuint fbo=0,tex=0,depth=0;glGenFramebuffers(1,&fbo);glGenTextures(1,&tex);glGenRenderbuffers(1,&depth);
 glBindFramebuffer(GL_FRAMEBUFFER,fbo);glActiveTexture(GL_TEXTURE0);glBindTexture(GL_TEXTURE_2D,tex);glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,w,h,0,GL_RGBA,GL_UNSIGNED_BYTE,nullptr);filtering(GL_TEXTURE_2D,GL_NEAREST);glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,tex,0);glBindRenderbuffer(GL_RENDERBUFFER,depth);glRenderbufferStorage(GL_RENDERBUFFER,GL_DEPTH_COMPONENT24,w,h);glFramebufferRenderbuffer(GL_FRAMEBUFFER,GL_DEPTH_ATTACHMENT,GL_RENDERBUFFER,depth);
 auto savedTool=tool_;auto cleanup=[&]{tool_=savedTool;glBindFramebuffer(GL_FRAMEBUFFER,0);glDeleteFramebuffers(1,&fbo);glDeleteTextures(1,&tex);glDeleteRenderbuffers(1,&depth);glViewport(0,0,width_,height_);glDisable(GL_SCISSOR_TEST);};
 try{check(glCheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE,"RGBA8 framebuffer incomplete");auto tool=tool_;tool_="NAVIGATE";draw(original,w,h);tool_=tool;Image result;result.width=w;result.height=h;result.rgba.resize(size_t(w)*h*4);glPixelStorei(GL_PACK_ALIGNMENT,1);glReadPixels(0,0,w,h,GL_RGBA,GL_UNSIGNED_BYTE,result.rgba.data());glCheck("readback");std::vector<uint8_t> row(w*4);for(int y=0;y<h/2;y++){auto* a=result.rgba.data()+size_t(y)*w*4;auto* b=result.rgba.data()+size_t(h-y-1)*w*4;std::memcpy(row.data(),a,w*4);std::memcpy(a,b,w*4);std::memcpy(b,row.data(),w*4);}cleanup();return result;}catch(...){cleanup();throw;}
}
void RendererSession::prepare(const Json& j){
 auto ops=j.value("operations",Json::array()),anchors=j.value("anchorOperations",Json::array());std::string protect=j.value("protectionId",std::string());protectRule_=j.value("protectionRuleId",std::string());
 check(ops.is_array()&&anchors.is_array()&&ops.size()<=8&&anchors.size()<=8,"Operation budget");const int w=asset_.image.width,h=asset_.image.height;std::vector<uint8_t> empty(size_t(w)*h,0);
 for(const auto* group:{&ops,&anchors})for(const auto& op:*group){std::string id=op.at("regionId");check(masks_.count(id)&&masks_.at(id).size()==empty.size(),"Region missing or wrong version");float strength=op.at("absoluteStrength");check(std::isfinite(strength)&&strength>=0&&strength<=.65,"Strength invalid");check(op.at("color").size()==3,"Color invalid");for(const auto& value:op.at("color")){float c=value;check(std::isfinite(c)&&c>=0&&c<=1,"Color range");}}
 check(protect.empty()||masks_.count(protect),"Protection missing");
 glActiveTexture(GL_TEXTURE1);glBindTexture(GL_TEXTURE_2D_ARRAY,maskArray_);for(int group=0;group<2;group++){const auto& operations=group?anchors:ops;for(int i=0;i<int(operations.size());i++){std::string id=operations[i]["regionId"];if(uploadedMasks_[group*8+i]==id)continue;
 if(!featherMasks_.count(id)){auto feather=innerFeather(masks_.at(id),w,h);if(!asset_.photo){check(masks_.count("editable"),"Editable atlas missing");const auto& editable=masks_.at("editable");for(size_t n=0;n<feather.size();n++)if(!editable[n])feather[n]=0;}featherMasks_[id]=std::move(feather);}
 glTexSubImage3D(GL_TEXTURE_2D_ARRAY,0,0,0,group*8+i,w,h,1,GL_RED,GL_UNSIGNED_BYTE,featherMasks_.at(id).data());uploadedMasks_[group*8+i]=id;}}
 glActiveTexture(GL_TEXTURE2);glBindTexture(GL_TEXTURE_2D,protection_);filtering(GL_TEXTURE_2D,GL_NEAREST);if(uploadedProtection_!=protect){glTexImage2D(GL_TEXTURE_2D,0,GL_R8,w,h,0,GL_RED,GL_UNSIGNED_BYTE,protect.empty()?empty.data():masks_.at(protect).data());uploadedProtection_=protect;}glCheck("prepare edit");operations_=ops;anchors_=anchors;protectId_=protect;
}
Result RendererSession::execute(const Json& j,const std::vector<uint8_t>& bytes){
 auto type=j.at("type").get<std::string>();if(type=="FOREGROUND"){foreground_=j.at("value");lastPresented_=0;nextAnimatedDraw_=0;if(foreground_){dirty_=true;schedule();}return {};}
 check(surface_!=EGL_NO_SURFACE,"Native surface unavailable");
 if(type=="ECHO")return {Json::object(),bytes};
 if(type=="NORMALIZE"){auto img=decodeImage(bytes);return {{{"width",img.width},{"height",img.height}},encodePNG(img)};}
 if(type=="LOAD"){Asset next=j.value("kind","")=="glb"?loadGLB(bytes):photoAsset(bytes);asset_=std::move(next);masks_.clear();featherMasks_.clear();operations_=Json::array();anchors_=Json::array();protectId_.clear();hasAsset_=true;upload();dirty_=true;schedule();return {{{"width",asset_.image.width},{"height",asset_.image.height},{"vertices",asset_.vertices.size()},{"triangles",asset_.indices.size()/3}}};}
 if(type=="MASK"){check(hasAsset_&&bytes.size()==size_t(asset_.image.width)*asset_.image.height,"Mask size");auto id=j.at("id").get<std::string>();masks_[id]=bytes;if(id=="editable"){featherMasks_.clear();uploadedMasks_.fill("");}else{featherMasks_.erase(id);for(auto& uploaded:uploadedMasks_)if(uploaded==id)uploaded="";}if(uploadedProtection_==id)uploadedProtection_="__uninitialized";return {};}
 if(type=="GET_VIEW"){orbit_=false;return {{{"yaw",yaw_},{"pitch",pitch_},{"distance",distance_},{"panX",panX_},{"panY",panY_}}};}
 if(type=="VIEW"){yaw_=asset_.photo?0:std::clamp(j.value("yaw",0.f),-3.14159265f,3.14159265f);pitch_=asset_.photo?0:std::clamp(j.value("pitch",0.f),-.6f,.6f);distance_=std::clamp(j.value("distance",16.f),10.f,25.f);panX_=j.value("panX",0.f);panY_=j.value("panY",0.f);orbit_=false;}
 else if(type=="TOOL"){tool_=j.at("tool");orbit_=false;}
 else if(type=="ORBIT"){orbit_=!asset_.photo;}
 else if(type=="ATMOSPHERE"){motion_=j.value("motion",false);auto palette=j.value("palette",std::string());palette_=palette=="warm"?1:palette=="clear"?2:0;if(!motion_)orbit_=false;}
 else if(type=="EDIT"){
  check(hasAsset_,"No asset");auto previous=operations_,anchors=anchors_;auto protection=protectId_,rule=protectRule_;
  int cw=std::min(width_,720),ch=std::min(2048,std::max(1,int(float(height_)*cw/width_)));
  auto reference=readFrame(cw,ch);auditMode_=1;auto oldCoverage=readFrame(cw,ch);auditMode_=0;
  size_t unchanged=0,protectedPixels=0;
  try{prepare(j);auto candidate=readFrame(cw,ch);auditMode_=1;auto coverage=readFrame(cw,ch);auditMode_=2;auto anchor=readFrame(cw,ch);auditMode_=0;
   for(size_t i=0;i<candidate.rgba.size();i+=4){bool protect=coverage.rgba[i+1]>0;
    bool allowed=coverage.rgba[i]>0||oldCoverage.rgba[i]>0||protect||oldCoverage.rgba[i+1]>0;
    if(protect){protectedPixels++;check(std::memcmp(candidate.rgba.data()+i,anchor.rgba.data()+i,4)==0,"Protected pixel changed");}
    if(!allowed){unchanged++;check(std::memcmp(candidate.rgba.data()+i,reference.rgba.data()+i,4)==0,"Unauthorized pixel changed");}
   }
  }catch(...){auditMode_=0;prepare({{"operations",previous},{"anchorOperations",anchors},{"protectionId",protection},{"protectionRuleId",rule}});throw;}
  dirty_=true;schedule();return {{{"checkedWidth",cw},{"checkedHeight",ch},{"protectedPixels",protectedPixels},{"nonAuthorizedPixels",unchanged},{"maxProtectedError",0},{"maxNonAuthorizedError",0}}, {}};
 }
 else if(type=="SNAPSHOT"){
  orbit_=false;std::string id=j.value("regionId",std::string());int w=j.value("width",768),h=j.value("height",1024);std::vector<Image> images;images.push_back(readFrame(w,h));
  try{if(!id.empty()){check(masks_.count(id),"Annotation region missing");glActiveTexture(GL_TEXTURE3);glBindTexture(GL_TEXTURE_2D,annotation_);filtering(GL_TEXTURE_2D,GL_NEAREST);glTexImage2D(GL_TEXTURE_2D,0,GL_R8,asset_.image.width,asset_.image.height,0,GL_RED,GL_UNSIGNED_BYTE,masks_.at(id).data());auditMode_=3;images.push_back(readFrame(w,h));auditMode_=0;}}catch(...){auditMode_=0;throw;}
  return {{{"width",w},{"height",h},{"view",{{"yaw",yaw_},{"pitch",pitch_},{"distance",distance_},{"panX",panX_},{"panY",panY_}}}},{},std::move(images)};
 }
 else if(type=="EXPORT"){orbit_=false;auto img=readFrame(j.value("width",768),j.value("height",1024),j.value("original",false));return {{{"width",img.width},{"height",img.height},{"generation",generation_}},{},{std::move(img)}};}
 else if(type=="SELECT"){orbit_=false;return {{{"width",asset_.image.width},{"height",asset_.image.height}},select(j.at("points"))};}
 else if(type=="PROBE")return probe();
 else if(type=="STATS"){auto sorted=frameTimes_,intervals=frameIntervals_;std::sort(sorted.begin(),sorted.end());std::sort(intervals.begin(),intervals.end());return {{{"frames",frameCount_},{"cpuSubmitAndSwapP50Ms",sorted.empty()?0:sorted[sorted.size()/2]},{"cpuSubmitAndSwapP95Ms",sorted.empty()?0:sorted[size_t((sorted.size()-1)*.95)]},{"cpuSubmitOver50Ms",std::count_if(sorted.begin(),sorted.end(),[](double t){return t>50;})},{"renderStartIntervalP50Ms",intervals.empty()?0:intervals[intervals.size()/2]},{"renderStartIntervalP95Ms",intervals.empty()?0:intervals[size_t((intervals.size()-1)*.95)]},{"renderStartIntervalOver50Ms",std::count_if(intervals.begin(),intervals.end(),[](double t){return t>50;})},{"generation",generation_},{"graphics",lastInfo_}}};}
 else if(type!="VIEW")throw std::runtime_error("Unknown native command");dirty_=true;schedule();return {};
}
Result RendererSession::probe(){
 auto old=std::move(asset_);bool had=hasAsset_;auto ops=operations_,anchors=anchors_;auto protection=protectId_;operations_=Json::array();anchors_=Json::array();protectId_.clear();
 asset_.vertices={{-5,-5,0,0,0,1,0,1},{5,-5,0,0,0,1,1,1},{5,5,0,0,0,1,1,0},{-5,5,0,0,0,1,0,0}};asset_.indices={0,1,2,0,2,3};asset_.image={2,2,{255,0,0,255,0,255,0,255,0,0,255,255,255,255,255,255}};hasAsset_=true;upload();asset_.image=decodeImage(encodePNG(asset_.image));upload();auto image=readFrame(64,64);
 auto red=[&](int x,int y){size_t i=(y*64+x)*4;return image.rgba[i]>220&&image.rgba[i+1]<40&&image.rgba[i+2]<40;};
 check(red(4,4),"Texture orientation/color: red must be top-left");
 size_t green=(4*64+59)*4,blue=(59*64+4)*4;check(image.rgba[green+1]>220&&image.rgba[blue+2]>220,"Texture quadrant orientation");
 auto png=encodePNG(image);auto decoded=decodeImage(png);check(decoded.rgba==image.rgba,"PNG roundtrip mismatch");
 asset_=std::move(old);hasAsset_=had;operations_=ops;anchors_=anchors;protectId_=protection;if(had)upload();
 return {{{"rgba8Fbo",true},{"pngRoundtripExact",true},{"graphics",lastInfo_}},png};
}
std::vector<uint8_t> RendererSession::select(const Json& points){
 check(hasAsset_,"No asset");auto editable=masks_.find("editable");
 check(asset_.photo||editable!=masks_.end(),"Editable atlas not registered");
 std::vector<uint8_t> all;if(asset_.photo)all.assign(size_t(asset_.image.width)*asset_.image.height,255);
 return visibleSelection(asset_,asset_.photo?all:editable->second,points,matrix(width_,height_),yaw_,pitch_,distance_,panX_,panY_);
}
}






