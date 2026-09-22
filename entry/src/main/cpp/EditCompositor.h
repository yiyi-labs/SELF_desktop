#pragma once
#include <vector>
#include <cstdint>
#include <algorithm>
#include <cmath>
namespace self {
inline std::vector<uint8_t> innerFeather(const std::vector<uint8_t>& mask,int w,int h){
 std::vector<int> d(mask.size(),1000000);for(int y=0;y<h;y++)for(int x=0;x<w;x++){int i=y*w+x;if(!mask[i]||x==0||y==0||x==w-1||y==h-1)d[i]=0;else d[i]=std::min(d[i],std::min(d[i-1]+1,d[i-w]+1));}
 for(int y=h-2;y>=0;y--)for(int x=w-2;x>=0;x--){int i=y*w+x;d[i]=std::min(d[i],std::min(d[i+1]+1,d[i+w]+1));}
 std::vector<uint8_t> result(mask.size());for(size_t i=0;i<mask.size();i++)result[i]=mask[i]?uint8_t(255*std::min(1.f,d[i]/3.f)+.5f):0;return result;
}
// Conservative inner distance falloff: never expands the authorized region.
// Two chamfer passes approximate Euclidean distance, including diagonal edges.
inline std::vector<uint8_t> adaptiveFeather(const std::vector<uint8_t>& mask,int w,int h){
 std::vector<float> d(mask.size(),float(w+h));size_t area=0;
 for(int y=0;y<h;y++)for(int x=0;x<w;x++){int i=y*w+x;if(!mask[i]||x==0||y==0||x==w-1||y==h-1)d[i]=0;else{area++;d[i]=std::min(d[i],std::min(d[i-1]+1,d[i-w]+1));d[i]=std::min(d[i],d[i-w-1]+1.414214f);if(x+1<w)d[i]=std::min(d[i],d[i-w+1]+1.414214f);}}
 for(int y=h-2;y>=0;y--)for(int x=w-2;x>=0;x--){int i=y*w+x;d[i]=std::min(d[i],std::min(d[i+1]+1,d[i+w]+1));d[i]=std::min(d[i],d[i+w+1]+1.414214f);if(x>0)d[i]=std::min(d[i],d[i+w-1]+1.414214f);}
 float maximum=*std::max_element(d.begin(),d.end());float radius=std::max(1.f,std::min({std::sqrt(float(area))*.12f,float(std::min(w,h))*.035f,maximum*.75f}));
 std::vector<uint8_t> result(mask.size());for(size_t i=0;i<mask.size();i++){float t=std::clamp(d[i]/radius,0.f,1.f);result[i]=mask[i]?uint8_t(mask[i]*t*t*(3-2*t)+.5f):0;}return result;
}
}
