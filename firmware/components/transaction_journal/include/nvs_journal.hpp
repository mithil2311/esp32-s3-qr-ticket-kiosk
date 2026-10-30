#pragma once
#include "journal.hpp"
#include "nvs.h"
namespace kiosk {
class NvsJournal:public Journal {
 nvs_handle_t handle_=0;bool opened_=false;
public:
 NvsJournal(){opened_=nvs_open("kiosk",NVS_READWRITE,&handle_)==ESP_OK;}
 ~NvsJournal(){if(opened_)nvs_close(handle_);}
 bool load(Record& r)override{
  if(!opened_)return false;StoredRecord stored{};size_t n=sizeof(stored);auto e=nvs_get_blob(handle_,"transaction",&stored,&n);if(e==ESP_ERR_NVS_NOT_FOUND)return true;
  if(e!=ESP_OK||n!=sizeof(stored)||crc32(&stored.record,sizeof(stored.record))!=stored.crc)return false;
  auto& t=stored.record;if(!std::memchr(t.operation,0,sizeof(t.operation))||!std::memchr(t.token,0,sizeof(t.token))||!std::memchr(t.device,0,sizeof(t.device))||!std::memchr(t.reservation,0,sizeof(t.reservation))||!std::memchr(t.title,0,sizeof(t.title)))return false;
  r=t;return true;
 }
 bool save(const Record& r)override{if(!opened_)return false;StoredRecord s{};s.record=r;s.crc=crc32(&s.record,sizeof(s.record));return nvs_set_blob(handle_,"transaction",&s,sizeof(s))==ESP_OK&&nvs_commit(handle_)==ESP_OK;}
};
}
