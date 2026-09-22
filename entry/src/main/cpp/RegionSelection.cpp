#include "RegionSelection.h"
#include <algorithm>
#include <numeric>
#include <cmath>
#include <stdexcept>
namespace self {
struct V {float x,y,z;V operator-(const V& b)const{return {x-b.x,y-b.y,z-b.z};}};
static float dot(V a,V b){return a.x*b.x+a.y*b.y+a.z*b.z;}
static V cross(V a,V b){return {a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x};}
static V pos(const Vertex& v){return {v.x,v.y,v.z};}
struct Node {V lo{1e30f,1e30f,1e30f},hi{-1e30f,-1e30f,-1e30f};int start=0,end=0,left=-1,right=-1;};
class Visibility {
 const Asset& a;std::vector<int> order;std::vector<Node> nodes;
 int build(int first,int last){Node node;node.start=first;node.end=last;for(int i=first;i<last;i++)for(int k=0;k<3;k++){auto p=pos(a.vertices[a.indices[order[i]*3+k]]);node.lo={std::min(node.lo.x,p.x),std::min(node.lo.y,p.y),std::min(node.lo.z,p.z)};node.hi={std::max(node.hi.x,p.x),std::max(node.hi.y,p.y),std::max(node.hi.z,p.z)};}int index=nodes.size();nodes.push_back(node);if(last-first>8){V ext=node.hi-node.lo;int axis=ext.x>ext.y?(ext.x>ext.z?0:2):(ext.y>ext.z?1:2);auto center=[&](int t){float value=0;for(int k=0;k<3;k++){const auto& v=a.vertices[a.indices[t*3+k]];value+=axis==0?v.x:axis==1?v.y:v.z;}return value;};int mid=(first+last)/2;std::nth_element(order.begin()+first,order.begin()+mid,order.begin()+last,[&](int x,int y){return center(x)<center(y);});int l=build(first,mid),r=build(mid,last);nodes[index].left=l;nodes[index].right=r;}return index;}
 bool box(const Node& n,V origin,V direction,float limit){float lo=0,hi=limit;for(int axis=0;axis<3;axis++){float o=axis==0?origin.x:axis==1?origin.y:origin.z,d=axis==0?direction.x:axis==1?direction.y:direction.z,mn=axis==0?n.lo.x:axis==1?n.lo.y:n.lo.z,mx=axis==0?n.hi.x:axis==1?n.hi.y:n.hi.z;if(std::abs(d)<1e-12f){if(o<mn||o>mx)return false;continue;}float a=(mn-o)/d,b=(mx-o)/d;if(a>b)std::swap(a,b);lo=std::max(lo,a);hi=std::min(hi,b);if(lo>hi)return false;}return true;}
 void visit(int i,V o,V d,float& closest,int& triangle){const auto& n=nodes[i];if(!box(n,o,d,closest))return;if(n.left>=0){visit(n.left,o,d,closest,triangle);visit(n.right,o,d,closest,triangle);return;}for(int k=n.start;k<n.end;k++){int t=order[k];V v0=pos(a.vertices[a.indices[t*3]]),e1=pos(a.vertices[a.indices[t*3+1]])-v0,e2=pos(a.vertices[a.indices[t*3+2]])-v0,p=cross(d,e2);float det=dot(e1,p);if(std::abs(det)<1e-9f)continue;float inv=1/det;V s=o-v0;float u=dot(s,p)*inv;if(u<0||u>1)continue;V q=cross(s,e1);float v=dot(d,q)*inv;if(v<0||u+v>1)continue;float distance=dot(e2,q)*inv;if(distance>0&&distance<closest){closest=distance;triangle=t;}}}
 public:explicit Visibility(const Asset& asset):a(asset){order.resize(a.indices.size()/3);std::iota(order.begin(),order.end(),0);build(0,order.size());}
 bool visible(V origin,V point,int triangle){V d=point-origin;float distance=std::sqrt(dot(d,d));d={d.x/distance,d.y/distance,d.z/distance};float closest=distance+.001f;int hit=-1;visit(0,origin,d,closest,hit);return hit==triangle&&std::abs(closest-distance)<.0001f;}
};
std::vector<uint8_t> visibleSelection(const Asset& a,const std::vector<uint8_t>& editable,const nlohmann::json& points,const std::array<float,16>& m,float yaw,float pitch,float distance,float panX,float panY){
 if(!points.is_array()||points.size()<3||points.size()>2048)throw std::runtime_error("Invalid lasso");for(const auto& p:points){if(!p.is_array()||p.size()!=2)throw std::runtime_error("Invalid point");for(const auto& v:p){float value=v;if(!std::isfinite(value)||value<0||value>1)throw std::runtime_error("Lasso outside viewport");}}
 int w=a.image.width,h=a.image.height;if(editable.size()!=size_t(w)*h)throw std::runtime_error("Editable atlas missing");
 auto edge=[](float ax,float ay,float bx,float by,float x,float y){return (x-ax)*(by-ay)-(y-ay)*(bx-ax);};
 auto inside=[&](float x,float y){bool in=false;for(size_t i=0,k=points.size()-1;i<points.size();k=i++){float ax=points[i][0],ay=points[i][1],bx=points[k][0],by=points[k][1];if((ay>y)!=(by>y)&&x<(bx-ax)*(y-ay)/(by-ay)+ax)in=!in;}return in;};
 // Inverse of R_x(pitch) R_y(yaw), for the exact same camera used by the renderer.
 float cx=std::cos(pitch),sx=std::sin(pitch),cy=std::cos(yaw),sy=std::sin(yaw);float x=-panX,y=-panY*cx+distance*sx,z=panY*sx+distance*cx;V origin{cy*x-sy*z,y,sy*x+cy*z};
 Visibility visibility(a);std::vector<uint8_t> result(size_t(w)*h,0);
 for(size_t t=0;t<a.indices.size();t+=3){const auto& v0=a.vertices[a.indices[t]];const auto& v1=a.vertices[a.indices[t+1]];const auto& v2=a.vertices[a.indices[t+2]];float area=edge(v0.u,v0.v,v1.u,v1.v,v2.u,v2.v);if(std::abs(area)<1e-12)continue;
 int x0=std::max(0,int(std::floor(std::min({v0.u,v1.u,v2.u})*w))),x1=std::min(w-1,int(std::ceil(std::max({v0.u,v1.u,v2.u})*w))),y0=std::max(0,int(std::floor(std::min({v0.v,v1.v,v2.v})*h))),y1=std::min(h-1,int(std::ceil(std::max({v0.v,v1.v,v2.v})*h)));
 for(int y=y0;y<=y1;y++)for(int x=x0;x<=x1;x++){if(!editable[size_t(y)*w+x])continue;float b0=edge(v1.u,v1.v,v2.u,v2.v,(x+.5f)/w,(y+.5f)/h)/area,b1=edge(v2.u,v2.v,v0.u,v0.v,(x+.5f)/w,(y+.5f)/h)/area,b2=1-b0-b1;if(b0<0||b1<0||b2<0)continue;V p{v0.x*b0+v1.x*b1+v2.x*b2,v0.y*b0+v1.y*b1+v2.y*b2,v0.z*b0+v1.z*b1+v2.z*b2};float q=m[3]*p.x+m[7]*p.y+m[11]*p.z+m[15];if(q<=0)continue;float screenX=(m[0]*p.x+m[4]*p.y+m[8]*p.z+m[12])/q*.5f+.5f,screenY=.5f-(m[1]*p.x+m[5]*p.y+m[9]*p.z+m[13])/q*.5f;if(inside(screenX,screenY)&&visibility.visible(origin,p,t/3))result[size_t(y)*w+x]=255;}}
 if(std::count(result.begin(),result.end(),255)==0)throw std::runtime_error("圈选内没有可编辑的可见面容，请换一个位置");return result;
}
}
