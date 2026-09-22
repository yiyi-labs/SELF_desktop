#pragma once
#include <vector>
#include <cstdint>
#include <algorithm>
namespace self {
inline std::vector<uint8_t> innerFeather(const std::vector<uint8_t>& mask,int w,int h){
 std::vector<int> d(mask.size(),1000000);for(int y=0;y<h;y++)for(int x=0;x<w;x++){int i=y*w+x;if(!mask[i]||x==0||y==0||x==w-1||y==h-1)d[i]=0;else d[i]=std::min(d[i],std::min(d[i-1]+1,d[i-w]+1));}
 for(int y=h-2;y>=0;y--)for(int x=w-2;x>=0;x--){int i=y*w+x;d[i]=std::min(d[i],std::min(d[i+1]+1,d[i+w]+1));}
 std::vector<uint8_t> result(mask.size());for(size_t i=0;i<mask.size();i++)result[i]=mask[i]?uint8_t(255*std::min(1.f,d[i]/3.f)+.5f):0;return result;
}
}
