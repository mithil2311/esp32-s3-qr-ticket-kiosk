#include "controller.hpp"
namespace kiosk {
const char* name(State s){
 switch(s){
#define S(x) case State::x:return #x
 S(BOOT);S(SELF_TEST);S(IDLE);S(QR_RECEIVED);S(VALIDATING);S(RETRY);S(RESERVED);S(PRINTING);S(PRINT_CONFIRMED);S(COMMITTING);S(SUCCESS);S(REJECTED);S(UNCERTAIN);S(RECOVERY);
#undef S
 }return "UNKNOWN";
}
void Controller::transition(State s,const char* reason){Json j;j.set("from",name(state_));j.set("state",name(s));j.set("reason",reason);j.set("operation_id",rec_.operation);j.set("t_us",double(p_.now_us()));j.set("queue_depth",double(size_));state_=s;p_.indicate(name(s));p_.emit("state",j.dump());}
bool Controller::persist(Stage s){rec_.stage=s;if(journal_.save(rec_))return true;locked_=true;transition(State::RECOVERY,"JOURNAL_FAILURE");return false;}
void Controller::boot(){
 transition(State::BOOT);transition(State::SELF_TEST);validation_start_=p_.now_us();
 if(device_.empty()||device_.size()>48||!journal_.load(rec_)||rec_.version!=1){locked_=true;transition(State::RECOVERY,"JOURNAL_OR_CONFIG_INVALID");return;}
 if(rec_.stage!=Stage::Empty&&device_!=rec_.device){locked_=true;transition(State::RECOVERY,"DEVICE_ID_CHANGED");return;}
 switch(rec_.stage){
  case Stage::Printing:if(!persist(Stage::Uncertain))return;[[fallthrough]];
  case Stage::Uncertain:transition(State::UNCERTAIN,"RESTART_UNCERTAIN_NO_REPRINT");break;
  case Stage::Created:case Stage::Reserved:reconcile_=true;transition(State::VALIDATING,"RESTART_RECONCILE");break;
  case Stage::Confirmed:reconcile_=true;transition(State::COMMITTING,"RESTART_COMMIT_ONLY");break;
  case Stage::Committed:std::snprintf(recent_[0].data(),97,"%s",rec_.token);recent_pos_=1;[[fallthrough]];
  case Stage::Rejected:case Stage::Empty:transition(State::IDLE);break;
  default:locked_=true;transition(State::RECOVERY,"INVALID_JOURNAL_STAGE");
 }
}
bool Controller::enqueue(const Scan& s){
 if(size_==queue_.size()){++overflow;++failures;Json j;j.set("reason","QUEUE_OVERFLOW");p_.emit("scan_drop",j.dump());return false;}
 queue_[(head_+size_)%queue_.size()]=s;++size_;if(size_>peak_queue)peak_queue=size_;return true;
}
void Controller::network_error(State target){
 ++attempts_;if(attempts_>=4){finish(false,"BACKEND_UNAVAILABLE");resume_=target;transition(State::RECOVERY,"BACKEND_UNAVAILABLE");return;}
 resume_=target;retry_start_=p_.now_us();next_=retry_start_+(100000ULL<<(attempts_-1));transition(State::RETRY,"BACKEND_RETRY");
}
void Controller::finish(bool success,const char* reason){
 if(success)++successes;else ++failures;
 if(!metric_active_)return;
 Json j;j.set("operation_id",rec_.operation);j.set("success",success);j.set("reason",reason);j.set("input_ms",input_ms_);j.set("validation_ms",validation_ms_);j.set("retry_ms",retry_ms_);j.set("generation_ms",generation_ms_);j.set("printing_ms",printing_ms_);j.set("total_ms",(p_.now_us()-begin_)/1000.0);j.set("end_to_end_ms",input_ms_+(p_.now_us()-begin_)/1000.0);j.set("queue_peak",double(peak_queue));p_.emit("metric",j.dump());metric_active_=false;
}
void Controller::apply(const Authorization& a){
 if(a.verdict==Verdict::Error){network_error(State::VALIDATING);return;}
 if(a.verdict==Verdict::Missing){reconcile_=false;return;}
 attempts_=0;reconcile_=false;validation_ms_=(p_.now_us()-validation_start_)/1000.0;
 if(a.verdict==Verdict::Denied){if(!persist(Stage::Rejected))return;finish(false,a.error.c_str());transition(State::REJECTED,a.error.c_str());return;}
 copy(rec_.reservation,a.reservation);copy(rec_.title,a.title);
 if(a.verdict==Verdict::Committed){if(!persist(Stage::Committed))return;finish(true,"RECONCILED_COMMIT");transition(State::SUCCESS);return;}
 if(!persist(Stage::Reserved))return;transition(State::RESERVED);
}
void Controller::print_result(PrintResult r){
 if(r==PrintResult::Pending){next_=p_.now_us()+20000;return;}
 printing_ms_=(p_.now_us()-print_start_)/1000.0;
 if(r==PrintResult::Confirmed){if(!persist(Stage::Confirmed))return;attempts_=0;transition(State::PRINT_CONFIRMED,"SIMULATOR_JOB_CONFIRMED");}
 else if(r==PrintResult::NotStarted){if(!persist(Stage::Reserved))return;resume_=State::VALIDATING;reconcile_=true;finish(false,"PRINTER_NOT_STARTED");transition(State::RECOVERY,"PRINTER_NOT_STARTED");}
 else {if(!persist(Stage::Uncertain))return;finish(false,"PRINT_UNCERTAIN");transition(State::UNCERTAIN,"PRINT_UNCERTAIN_NO_REPRINT");}
}
void Controller::tick(){
 auto now=p_.now_us();
 switch(state_){
 case State::IDLE:{
  if(!size_)return;
  Scan s=queue_[head_];head_=(head_+1)%queue_.size();--size_;
  if(!Scanner::valid(s.token)){++malformed;++failures;Json j;j.set("reason","MALFORMED_QR");p_.emit("scan_drop",j.dump());return;}
  bool duplicate=false;for(auto& t:recent_)if(!std::strcmp(t.data(),s.token))duplicate=true;
  if(duplicate){++suppressed;Json j;j.set("reason","LOCAL_DUPLICATE");p_.emit("scan_drop",j.dump());return;}
  std::snprintf(recent_[recent_pos_++%recent_.size()].data(),97,"%s",s.token);
  rec_=Record{};copy(rec_.device,device_);copy(rec_.token,s.token);p_.random_id(rec_.operation);
  metric_active_=true;begin_=s.received_us;input_ms_=(s.received_us-s.input_us)/1000.0;validation_ms_=generation_ms_=printing_ms_=retry_ms_=0;
  transition(State::QR_RECEIVED);if(!persist(Stage::Created))return;validation_start_=now;attempts_=0;reconcile_=false;transition(State::VALIDATING);return;
 }
 case State::VALIDATING:apply(reconcile_?backend_.lookup(rec_):backend_.reserve(rec_));return;
 case State::RESERVED:{
  if(!persist(Stage::Printing))return;auto start=p_.now_us();auto bytes=EscPos::ticket(rec_);generation_ms_=(p_.now_us()-start)/1000.0;print_start_=p_.now_us();transition(State::PRINTING);print_result(printer_.start(rec_,bytes));return;
 }
 case State::PRINTING:
  if(now-print_start_>10000000){print_result(PrintResult::Uncertain);return;}
  if(now>=next_)print_result(printer_.poll(rec_));return;
 case State::PRINT_CONFIRMED:transition(State::COMMITTING);return;
 case State::COMMITTING:{
  auto a=reconcile_?backend_.lookup(rec_):backend_.commit(rec_);
  if(a.verdict==Verdict::Committed){if(!persist(Stage::Committed))return;attempts_=0;finish(true,"COMMITTED");transition(State::SUCCESS);}
  else if(a.verdict==Verdict::Reserved&&reconcile_){reconcile_=false;}
  else network_error(State::COMMITTING);
  return;
 }
 case State::RETRY:if(now>=next_){retry_ms_+=(now-retry_start_)/1000.0;transition(resume_);}return;
 case State::SUCCESS:case State::REJECTED:transition(State::IDLE);return;
 default:return;
 }
}
bool Controller::retry(){if(state_!=State::RECOVERY||locked_)return false;attempts_=0;transition(resume_,"OPERATOR_RETRY");return true;}
bool Controller::resolve_printed(){if(state_!=State::UNCERTAIN||locked_)return false;if(!persist(Stage::Confirmed))return false;attempts_=0;reconcile_=true;transition(State::COMMITTING,"OPERATOR_VERIFIED_PRINTED");return true;}
std::string Controller::status()const{Json j;j.set("state",name(state_));j.set("operation_id",rec_.operation);j.set("stage",double(uint32_t(rec_.stage)));j.set("queue_depth",double(size_));j.set("queue_peak",double(peak_queue));j.set("successes",double(successes));j.set("failures",double(failures));j.set("overflow",double(overflow));j.set("suppressed",double(suppressed));j.set("malformed",double(malformed));j.set("locked",locked_);return j.dump();}
}
