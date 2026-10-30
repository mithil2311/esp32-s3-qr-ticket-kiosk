#pragma once
#include "journal.hpp"
namespace kiosk {
struct EscPos {
 static std::string ticket(const Record& r){
  std::string b="\x1b@";b+="\x1b\x61\x01";b+="\x1b\x45\x01";b+="\x1d\x21\x11";
  b+="ADMISSION TICKET\n";b.append("\x1d\x21\x00",3);b.append("\x1b\x45\x00",3);
  b+=r.title;b+='\n';b.append("\x1b\x61\x00",3);b+="Ticket: ";b+=r.token;b+="\nOperation: ";b+=r.operation;b+='\n';
  b+="\x1b\x64\x03";b+="\x1d\x56\x01";return b;
 }
 static std::string hex(const std::string& b){const char* h="0123456789abcdef";std::string s;s.reserve(2*b.size());for(unsigned char c:b){s+=h[c>>4];s+=h[c&15];}return s;}
};
enum class PrintResult {Pending,Confirmed,NotStarted,Uncertain};
struct Printer {virtual ~Printer()=default;virtual PrintResult start(const Record&,const std::string&)=0;virtual PrintResult poll(const Record&)=0;};
class VirtualPrinterTransport: public Printer {
 Http& http_;
 PrintResult decode(const HttpResponse& r,const Record& rec){
  if(r.status!=200||!valid_json(r.body))return PrintResult::Uncertain;
  Json j(cJSON_Parse(r.body.c_str()));if(j.str("operation_id")!=rec.operation)return PrintResult::Uncertain;
  auto s=j.str("outcome");if(s=="confirmed")return PrintResult::Confirmed;if(s=="pending")return PrintResult::Pending;if(s=="not_started")return PrintResult::NotStarted;return PrintResult::Uncertain;
 }
public:
 explicit VirtualPrinterTransport(Http& h):http_(h){}
 PrintResult start(const Record& r,const std::string& b)override{Json j;j.set("operation_id",r.operation);j.set("escpos_hex",EscPos::hex(b));return decode(http_.request("/printer/jobs",j.dump()),r);}
 PrintResult poll(const Record& r)override{return decode(http_.request(std::string("/printer/jobs/")+r.operation,"","GET"),r);}
};
// Physical USB Host/Bluetooth transports cannot claim completion without verified status semantics.
class UnconfiguredHardwarePrinter:public Printer {
 PrintResult start(const Record&,const std::string&)override{return PrintResult::NotStarted;}
 PrintResult poll(const Record&)override{return PrintResult::Uncertain;}
};
}
