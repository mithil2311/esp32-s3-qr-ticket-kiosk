#pragma once
#include "kiosk_hal.hpp"
#include "indicator.hpp"
#include "esp_timer.h"
#include "esp_random.h"
#include "esp_http_client.h"
namespace kiosk {
class EspPlatform:public Platform {
 Indicator& indicator_;
public:
 explicit EspPlatform(Indicator& i):indicator_(i){}
 uint64_t now_us()override{return esp_timer_get_time();}
 void random_id(char out[33])override{uint8_t b[16];esp_fill_random(b,sizeof(b));const char* h="0123456789abcdef";for(int i=0;i<16;++i){out[2*i]=h[b[i]>>4];out[2*i+1]=h[b[i]&15];}out[32]=0;}
 void emit(const char* e,const std::string& json)override{std::printf("{\"event\":\"%s\",\"data\":%s}\n",e,json.c_str());std::fflush(stdout);}
 void indicate(const char* state)override{indicator_.state(state,esp_timer_get_time());}
};
class EspHttp:public Http {
 std::string base_;
 struct Buffer{std::string body;bool overflow=false;};
 static esp_err_t event(esp_http_client_event_t* e){auto b=static_cast<Buffer*>(e->user_data);if(e->event_id==HTTP_EVENT_ON_DATA){if(b->body.size()+e->data_len>8192){b->overflow=true;return ESP_FAIL;}b->body.append(static_cast<const char*>(e->data),e->data_len);}return ESP_OK;}
public:
 explicit EspHttp(std::string base):base_(std::move(base)){}
 HttpResponse request(const std::string& path,const std::string& body,const char* method)override{
  std::string url=base_+path;Buffer b;esp_http_client_config_t cfg{};cfg.url=url.c_str();cfg.timeout_ms=1000;cfg.event_handler=event;cfg.user_data=&b;cfg.disable_auto_redirect=true;
  auto client=esp_http_client_init(&cfg);if(!client)return {};
  esp_http_client_set_method(client,!std::strcmp(method,"GET")?HTTP_METHOD_GET:HTTP_METHOD_POST);
  esp_http_client_set_header(client,"Content-Type","application/json");
  if(!body.empty())esp_http_client_set_post_field(client,body.data(),body.size());
  auto result=esp_http_client_perform(client);int code=esp_http_client_get_status_code(client);esp_http_client_cleanup(client);return result==ESP_OK&&!b.overflow?HttpResponse{code,b.body}:HttpResponse{};
 }
};
}
