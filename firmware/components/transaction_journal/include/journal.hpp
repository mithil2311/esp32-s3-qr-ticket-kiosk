#pragma once
#include "kiosk_hal.hpp"
namespace kiosk {
enum class Stage:uint32_t {Empty,Created,Reserved,Printing,Confirmed,Committed,Rejected,Uncertain};
struct Record {
 uint32_t version=1;
 Stage stage=Stage::Empty;
 char operation[33]{};
 char token[70]{};
 char device[49]{};
 char reservation[65]{};
 char title[97]{};
};
struct Journal {virtual ~Journal()=default;virtual bool load(Record&)=0;virtual bool save(const Record&)=0;};
struct StoredRecord {Record record;uint32_t crc;};
}
