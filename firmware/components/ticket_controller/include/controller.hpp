#pragma once
#include "scanner.hpp"
#include "backend.hpp"
#include "printer.hpp"
namespace kiosk {
enum class State {BOOT,SELF_TEST,IDLE,QR_RECEIVED,VALIDATING,RETRY,RESERVED,PRINTING,PRINT_CONFIRMED,COMMITTING,SUCCESS,REJECTED,UNCERTAIN,RECOVERY};
const char* name(State s);
class Controller {
 Platform& p_;Journal& journal_;Backend& backend_;Printer& printer_;std::string device_;
 Record rec_{};State state_=State::BOOT,resume_=State::VALIDATING;
 std::array<Scan,8> queue_{};size_t head_=0,size_=0;
 std::array<std::array<char,97>,32> recent_{};size_t recent_pos_=0;
 bool locked_=false,reconcile_=false,metric_active_=false;
 uint64_t next_=0,begin_=0,validation_start_=0,print_start_=0,retry_start_=0;
 double input_ms_=0,validation_ms_=0,generation_ms_=0,printing_ms_=0,retry_ms_=0;
 unsigned attempts_=0;
 void transition(State s,const char* reason="");bool persist(Stage s);void network_error(State target);
 void apply(const Authorization& a);void print_result(PrintResult r);void finish(bool success,const char* reason);
public:
 uint32_t successes=0,failures=0,overflow=0,suppressed=0,malformed=0,peak_queue=0;
 Controller(Platform& p,Journal& j,Backend& b,Printer& pr,std::string device):p_(p),journal_(j),backend_(b),printer_(pr),device_(std::move(device)){}
 void boot();bool enqueue(const Scan&);void tick();bool retry();bool resolve_printed();
 State state()const{return state_;}const Record& record()const{return rec_;}size_t depth()const{return size_;}
 std::string status()const;
};
}
