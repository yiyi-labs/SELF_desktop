#include "GltfAssetLoader.h"
#define CGLTF_IMPLEMENTATION
#include "vendor/cgltf.h"
#include <memory>
#include <stdexcept>
#include <cmath>
#include <string>
namespace self {
static void require(bool value,const char* error){if(!value)throw std::runtime_error(error);}
Asset loadGLB(const std::vector<uint8_t>& bytes){
 require(bytes.size()>=20&&bytes.size()<=32*1024*1024,"GLB size");
 cgltf_options options{};cgltf_data* raw=nullptr;require(cgltf_parse(&options,bytes.data(),bytes.size(),&raw)==cgltf_result_success,"GLB parse");
 std::unique_ptr<cgltf_data,decltype(&cgltf_free)> data(raw,cgltf_free);
 require(raw->file_type==cgltf_file_type_glb&&raw->buffers_count==1&&!raw->buffers[0].uri,"Self-contained GLB required");
 require(cgltf_load_buffers(&options,raw,nullptr)==cgltf_result_success&&cgltf_validate(raw)==cgltf_result_success,"Invalid GLB buffers/accessors");
 require(raw->skins_count==0&&raw->animations_count==0,"Skins and animations unsupported");
 for(size_t i=0;i<raw->extensions_used_count;i++)require(std::string(raw->extensions_used[i])=="KHR_materials_unlit","Unsupported glTF extension");
 require(raw->meshes_count==1&&raw->meshes[0].primitives_count==1,"Profile requires one mesh / primitive");
 cgltf_node* node=nullptr;for(size_t i=0;i<raw->nodes_count;i++)if(raw->nodes[i].mesh){require(!node,"Instanced meshes unsupported");node=&raw->nodes[i];}
 require(node!=nullptr,"No mesh node");
 auto& primitive=raw->meshes[0].primitives[0];require(primitive.type==cgltf_primitive_type_triangles&&primitive.targets_count==0&&primitive.indices,"Indexed static triangles required");
 require(!primitive.has_draco_mesh_compression,"Draco unsupported");
 for(size_t i=0;i<raw->accessors_count;i++)require(!raw->accessors[i].is_sparse,"Sparse accessor unsupported");
 auto pos=cgltf_find_accessor(&primitive,cgltf_attribute_type_position,0),normal=cgltf_find_accessor(&primitive,cgltf_attribute_type_normal,0),uv=cgltf_find_accessor(&primitive,cgltf_attribute_type_texcoord,0);
 require(pos&&normal&&uv&&pos->count==normal->count&&uv->count==pos->count&&pos->count<=150000,"POSITION/NORMAL/UV required or budget exceeded");
 require(primitive.indices->count%3==0&&primitive.indices->count<=300000,"Triangle index budget");
 auto material=primitive.material;require(material&&material->has_pbr_metallic_roughness&&material->alpha_mode==cgltf_alpha_mode_opaque,"Opaque baked material required");
 for(float factor:material->pbr_metallic_roughness.base_color_factor)require(std::abs(factor-1)<.00001,"Non-neutral material factor unsupported");
 auto& texture=material->pbr_metallic_roughness.base_color_texture;require(texture.texture&&texture.texcoord==0&&!texture.has_transform,"UV0 texture required");
 auto image=texture.texture->image;require(image&&image->buffer_view&&!image->uri,"Embedded PNG/JPEG required");
 std::string mime=image->mime_type?image->mime_type:"";require(mime=="image/png"||mime=="image/jpeg","Image format");
 const auto* start=cgltf_buffer_view_data(image->buffer_view);require(start,"Image buffer");
 Asset result;result.image=decodeImage(std::vector<uint8_t>(start,start+image->buffer_view->size));
 float transform[16];cgltf_node_transform_world(node,transform);
 result.vertices.reserve(pos->count);
 for(size_t i=0;i<pos->count;i++){
  float p[3],n[3],t[2];require(cgltf_accessor_read_float(pos,i,p,3)&&cgltf_accessor_read_float(normal,i,n,3)&&cgltf_accessor_read_float(uv,i,t,2),"Accessor read");
  for(float v:p)require(std::isfinite(v),"Nonfinite position");for(float v:t)require(std::isfinite(v)&&v>=0&&v<=1,"UV outside supported atlas");
  // cgltf handles byteOffset/stride/component types/normalized. Bake world node transform once.
  result.vertices.push_back({transform[0]*p[0]+transform[4]*p[1]+transform[8]*p[2]+transform[12],transform[1]*p[0]+transform[5]*p[1]+transform[9]*p[2]+transform[13],transform[2]*p[0]+transform[6]*p[1]+transform[10]*p[2]+transform[14],n[0],n[1],n[2],t[0],t[1]});
 }
 for(size_t i=0;i<primitive.indices->count;i++){auto index=cgltf_accessor_read_index(primitive.indices,i);require(index<pos->count,"Index out of bounds");result.indices.push_back(index);}
 return result;
}
Asset photoAsset(const std::vector<uint8_t>& bytes){Asset a;a.image=decodeImage(bytes);a.photo=true;float x=4.f*a.image.width/a.image.height;a.vertices={{-x,-4,0,0,0,1,0,1},{x,-4,0,0,0,1,1,1},{x,4,0,0,0,1,1,0},{-x,4,0,0,0,1,0,0}};a.indices={0,1,2,0,2,3};return a;}
}
