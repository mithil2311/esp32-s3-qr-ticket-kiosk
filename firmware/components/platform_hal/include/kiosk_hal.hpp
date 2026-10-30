#pragma once
#include <array>
#include <cstdint>
#include <string>
#include <memory>
#include <cstring>
#include <cstdio>
#include "cJSON.h"
namespace kiosk {
struct Json {
 cJSON* p;
 explicit Json(cJSON* v=nullptr):p(v?v:cJSON_CreateObject()){}
 ~Json(){cJSON_Delete(p);} Json(const Json&)=delete; Json& operator=(const Json&)=delete;
 void set(const char* k,const std::string& v){cJSON_AddStringToObject(p,k,v.c_str());}
 void set(const char* k,const char* v){cJSON_AddStringToObject(p,k,v);}
 void set(const char* k,double v){cJSON_AddNumberToObject(p,k,v);}
 void set(const char* k,bool v){cJSON_AddBoolToObject(p,k,v);}
 std::string str(const char* k)const{auto v=cJSON_GetObjectItemCaseSensitive(p,k);return cJSON_IsString(v)?v->valuestring:"";}
 double num(const char* k,double d=0)const{auto v=cJSON_GetObjectItemCaseSensitive(p,k);return cJSON_IsNumber(v)?v->valuedouble:d;}
 bool boolean(const char* k)const{return cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(p,k));}
 std::string dump()const{char* s=cJSON_PrintUnformatted(p);std::string out=s?s:"{}";cJSON_free(s);return out;}
};
inline bool valid_json(const std::string& s){auto p=cJSON_Parse(s.c_str());bool ok=cJSON_IsObject(p);cJSON_Delete(p);return ok;}
struct HttpResponse {int status=0;std::string body;};
struct Http {virtual ~Http()=default;virtual HttpResponse request(const std::string&,const std::string&,const char* method="POST")=0;};
struct Platform {
 virtual ~Platform()=default;
 virtual uint64_t now_us()=0;
 virtual void random_id(char out[33])=0;
 virtual void emit(const char* event,const std::string& json)=0;
 virtual void indicate(const char* state)=0;
};
template<size_t N> inline void copy(char (&out)[N],const std::string& s){std::snprintf(out,N,"%s",s.c_str());}
inline uint32_t crc32(const void* p,size_t n){uint32_t c=~0U;auto b=static_cast<const uint8_t*>(p);while(n--){c^=*b++;for(int i=0;i<8;++i)c=(c>>1)^(0xEDB88320U& (0U-(c&1U)));}return ~c;}
}
