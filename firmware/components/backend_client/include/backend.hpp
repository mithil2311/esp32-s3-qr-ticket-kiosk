#pragma once
#include "journal.hpp"
namespace kiosk {
enum class Verdict {Reserved,Committed,Denied,Missing,Error};
struct Authorization {Verdict verdict=Verdict::Error;std::string reservation,title,error;};
class Backend {
 Http& http_;
 Authorization decode(const HttpResponse& r,const Record& rec){
  if(r.status==404)return {Verdict::Missing,"","","NOT_FOUND"};
  if(r.status!=200||!valid_json(r.body))return {Verdict::Error,"","","NETWORK_OR_PROTOCOL"};
  Json j(cJSON_Parse(r.body.c_str()));
  if(j.str("operation_id")!=rec.operation||j.str("device_id")!=rec.device||j.str("ticket_token")!=rec.token)return {Verdict::Error,"","","IDENTITY_MISMATCH"};
  auto status=j.str("status");auto res=j.str("reservation_id");
  if(status=="denied")return {Verdict::Denied,"","",j.str("error_code")};
  if(!j.boolean("authorized")||res.empty()||res.size()>64)return {Verdict::Error,"","","INVALID_AUTHORIZATION"};
  if(rec.reservation[0]&&res!=rec.reservation)return {Verdict::Error,"","","RESERVATION_MISMATCH"};
  auto title=j.str("title");if(title.size()>96)return {Verdict::Error,"","","INVALID_METADATA"};
  for(unsigned char c:title)if(c<32||c>126)return {Verdict::Error,"","","INVALID_METADATA"};
  if(status=="reserved")return {Verdict::Reserved,res,title,""};
  if(status=="committed")return {Verdict::Committed,res,title,""};
  return {Verdict::Error,"","","INVALID_STATUS"};
 }
 std::string body(const Record& r){Json j;j.set("ticket_token",r.token);j.set("device_id",r.device);j.set("operation_id",r.operation);j.set("reservation_id",r.reservation);return j.dump();}
public:
 explicit Backend(Http& h):http_(h){}
 Authorization reserve(const Record& r){return decode(http_.request("/api/tickets/reserve",body(r)),r);}
 Authorization lookup(const Record& r){return decode(http_.request(std::string("/api/operations/")+r.operation,"","GET"),r);}
 Authorization commit(const Record& r){return decode(http_.request("/api/tickets/commit",body(r)),r);}
};
}
