#include "ImagePipeline.h"
#include "PhotoOrientation.h"
#include <multimedia/image_framework/image/image_source_native.h>
#include <multimedia/image_framework/image/pixelmap_native.h>
#include <multimedia/image_framework/image/image_packer_native.h>
#include <stdexcept>
#include <cstring>
#include <memory>
#include <string>
namespace self {
static void ok(Image_ErrorCode code,const char* step){if(code!=IMAGE_SUCCESS)throw std::runtime_error(std::string(step)+": "+std::to_string(code));}
Image decodeImage(const std::vector<uint8_t>& data){
 OH_ImageSourceNative* raw=nullptr;ok(OH_ImageSourceNative_CreateFromData(const_cast<uint8_t*>(data.data()),data.size(),&raw),"image source");
 std::unique_ptr<OH_ImageSourceNative,decltype(&OH_ImageSourceNative_Release)> source(raw,OH_ImageSourceNative_Release);
 OH_DecodingOptions* options=nullptr;ok(OH_DecodingOptions_Create(&options),"decode options");
 std::unique_ptr<OH_DecodingOptions,decltype(&OH_DecodingOptions_Release)> opts(options,OH_DecodingOptions_Release);
 ok(OH_DecodingOptions_SetPixelFormat(options,3),"RGBA8888");
 OH_PixelmapNative* pixels=nullptr;ok(OH_ImageSourceNative_CreatePixelmap(raw,options,&pixels),"decode");
 std::unique_ptr<OH_PixelmapNative,decltype(&OH_PixelmapNative_Release)> map(pixels,OH_PixelmapNative_Release);
 OH_Pixelmap_ImageInfo* info=nullptr;ok(OH_PixelmapImageInfo_Create(&info),"image info");
 std::unique_ptr<OH_Pixelmap_ImageInfo,decltype(&OH_PixelmapImageInfo_Release)> inf(info,OH_PixelmapImageInfo_Release);
 ok(OH_PixelmapNative_GetImageInfo(pixels,info),"pixel info");
 uint32_t w=0,h=0,stride=0;int32_t format=0;OH_PixelmapImageInfo_GetWidth(info,&w);OH_PixelmapImageInfo_GetHeight(info,&h);OH_PixelmapImageInfo_GetRowStride(info,&stride);OH_PixelmapImageInfo_GetPixelFormat(info,&format);
 if(!w||!h||w>4096||h>4096||format!=3||stride<w*4)throw std::runtime_error("Unsupported image dimensions/stride/format");
 std::vector<uint8_t> padded(size_t(stride)*h);size_t length=padded.size();ok(OH_PixelmapNative_ReadPixels(pixels,padded.data(),&length),"read pixels");
 Image result;result.width=w;result.height=h;result.rgba.resize(size_t(w)*h*4);
 for(uint32_t y=0;y<h;y++)std::memcpy(result.rgba.data()+size_t(y)*w*4,padded.data()+size_t(y)*stride,w*4);
 // Opaque baked appearance is the supported profile; reject partial alpha instead of silently premultiplying twice.
 for(size_t i=3;i<result.rgba.size();i+=4)if(result.rgba[i]!=255)throw std::runtime_error("Only opaque baseline images are supported");
 return orientImage(std::move(result),exifOrientation(data));
}
std::vector<uint8_t> encodePNG(const Image& image){
 OH_Pixelmap_InitializationOptions* opt=nullptr;ok(OH_PixelmapInitializationOptions_Create(&opt),"pixel options");
 std::unique_ptr<OH_Pixelmap_InitializationOptions,decltype(&OH_PixelmapInitializationOptions_Release)> opts(opt,OH_PixelmapInitializationOptions_Release);
 ok(OH_PixelmapInitializationOptions_SetWidth(opt,image.width),"width");ok(OH_PixelmapInitializationOptions_SetHeight(opt,image.height),"height");
 ok(OH_PixelmapInitializationOptions_SetPixelFormat(opt,3),"format");ok(OH_PixelmapInitializationOptions_SetSrcPixelFormat(opt,3),"source format");
 ok(OH_PixelmapInitializationOptions_SetAlphaType(opt,3),"unpremultiplied alpha");
 OH_PixelmapNative* pix=nullptr;ok(OH_PixelmapNative_CreatePixelmap(const_cast<uint8_t*>(image.rgba.data()),image.rgba.size(),opt,&pix),"create export pixels");
 std::unique_ptr<OH_PixelmapNative,decltype(&OH_PixelmapNative_Release)> pixels(pix,OH_PixelmapNative_Release);
 OH_ImagePackerNative* pack=nullptr;ok(OH_ImagePackerNative_Create(&pack),"packer");
 std::unique_ptr<OH_ImagePackerNative,decltype(&OH_ImagePackerNative_Release)> packer(pack,OH_ImagePackerNative_Release);
 OH_PackingOptions* popt=nullptr;ok(OH_PackingOptions_Create(&popt),"pack options");
 std::unique_ptr<OH_PackingOptions,decltype(&OH_PackingOptions_Release)> po(popt,OH_PackingOptions_Release);
 char mime[]="image/png";Image_MimeType type{mime,9};ok(OH_PackingOptions_SetMimeType(popt,&type),"PNG MIME");OH_PackingOptions_SetQuality(popt,100);
 std::vector<uint8_t> bytes(image.rgba.size()+65536);size_t size=bytes.size();ok(OH_ImagePackerNative_PackToDataFromPixelmap(pack,popt,pix,bytes.data(),&size),"PNG encoding");bytes.resize(size);return bytes;
}
}
