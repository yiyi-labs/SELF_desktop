#pragma once
#include <vector>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include "ImagePipeline.h"
namespace self {
// JPEG APP1 EXIF orientation. No second implicit mirror is applied for imported photographs.
inline int exifOrientation(const std::vector<uint8_t>& bytes){
 if(bytes.size()<4||bytes[0]!=255||bytes[1]!=216)return 1;size_t p=2;
 while(p+4<=bytes.size()){if(bytes[p]!=255)break;uint8_t marker=bytes[p+1];if(marker==218||marker==217)break;size_t size=(bytes[p+2]<<8)|bytes[p+3];if(size<2||p+2+size>bytes.size())throw std::runtime_error("Malformed JPEG marker");
  if(marker==225&&size>=16&&std::memcmp(bytes.data()+p+4,"Exif\0\0",6)==0){size_t base=p+10,end=p+2+size;bool little=bytes[base]=='I'&&bytes[base+1]=='I';bool big=bytes[base]=='M'&&bytes[base+1]=='M';if(!little&&!big)throw std::runtime_error("Malformed EXIF byte order");
   auto u16=[&](size_t n)->uint16_t{if(n+2>end)throw std::runtime_error("EXIF bounds");return little?bytes[n]|(bytes[n+1]<<8):(bytes[n]<<8)|bytes[n+1];};
   auto u32=[&](size_t n)->uint32_t{if(n+4>end)throw std::runtime_error("EXIF bounds");return little?uint32_t(bytes[n])|(uint32_t(bytes[n+1])<<8)|(uint32_t(bytes[n+2])<<16)|(uint32_t(bytes[n+3])<<24):(uint32_t(bytes[n])<<24)|(uint32_t(bytes[n+1])<<16)|(uint32_t(bytes[n+2])<<8)|bytes[n+3];};
   size_t ifd=base+u32(base+4);uint16_t count=u16(ifd);if(count>4096)throw std::runtime_error("EXIF entry budget");for(size_t i=0;i<count;i++){size_t n=ifd+2+i*12;if(u16(n)==0x112){if(u16(n+2)!=3||u32(n+4)!=1)throw std::runtime_error("EXIF orientation type");int orientation=u16(n+8);if(orientation<1||orientation>8)throw std::runtime_error("EXIF orientation range");return orientation;}}return 1;
  }p+=2+size;
 }return 1;
}
inline Image orientImage(Image source,int orientation){
 if(orientation==1)return source;Image out;out.width=orientation>=5?source.height:source.width;out.height=orientation>=5?source.width:source.height;out.rgba.resize(source.rgba.size());
 for(int y=0;y<source.height;y++)for(int x=0;x<source.width;x++){int nx=x,ny=y;switch(orientation){case 2:nx=source.width-1-x;break;case 3:nx=source.width-1-x;ny=source.height-1-y;break;case 4:ny=source.height-1-y;break;case 5:nx=y;ny=x;break;case 6:nx=source.height-1-y;ny=x;break;case 7:nx=source.height-1-y;ny=source.width-1-x;break;case 8:nx=y;ny=source.width-1-x;break;}std::memcpy(out.rgba.data()+(size_t(ny)*out.width+nx)*4,source.rgba.data()+(size_t(y)*source.width+x)*4,4);}return out;
}
}
