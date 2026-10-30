#include "controller.hpp"
#include <chrono>
#include <cctype>
#include <cerrno>
#include <cstdlib>
#include <fcntl.h>
#include <iostream>
#include <unistd.h>
#include <sys/file.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/resource.h>
#include <poll.h>
#include <arpa/inet.h>
#include <malloc.h>
#include <filesystem>
#include <stdexcept>
using namespace kiosk;
uint64_t monotonic_us(){return std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();}
class Fd {
 int fd_;
public:explicit Fd(int fd):fd_(fd){}~Fd(){if(fd_>=0)::close(fd_);}Fd(const Fd&)=delete;operator int()const{return fd_;}
};
class HostHttp:public Http {
 std::string host_,prefix_;int port_;int timeout_;
public:
 HostHttp(const std::string& url,int timeout):timeout_(timeout){
  if(url.rfind("http://",0)!=0)throw std::runtime_error("Host simulation requires http://IPv4:port");
  auto end=url.find('/',7);auto authority=url.substr(7,end==std::string::npos?end:end-7);auto colon=authority.find(':');host_=authority.substr(0,colon);port_=colon==std::string::npos?80:std::stoi(authority.substr(colon+1));prefix_=end==std::string::npos?"":url.substr(end);
 }
 HttpResponse request(const std::string& path,const std::string& body,const char* method)override{
  Fd fd(::socket(AF_INET,SOCK_STREAM|SOCK_NONBLOCK,0));if(fd<0)return {};
  sockaddr_in addr{};addr.sin_family=AF_INET;addr.sin_port=htons(port_);if(inet_pton(AF_INET,host_.c_str(),&addr.sin_addr)!=1)return {};
  uint64_t deadline=monotonic_us()+uint64_t(timeout_)*1000;
  auto ready=[&](short events){auto now=monotonic_us();if(now>=deadline)return false;pollfd pfd{fd,events,0};return ::poll(&pfd,1,int((deadline-now+999)/1000))>0;};
  if(::connect(fd,reinterpret_cast<sockaddr*>(&addr),sizeof(addr))<0&&errno!=EINPROGRESS)return {};
  if(!ready(POLLOUT))return {};int err=0;socklen_t len=sizeof(err);if(getsockopt(fd,SOL_SOCKET,SO_ERROR,&err,&len)||err)return {};
  std::string req=std::string(method)+" "+prefix_+path+" HTTP/1.0\r\nHost: "+host_+"\r\nContent-Type: application/json\r\nContent-Length: "+std::to_string(body.size())+"\r\nConnection: close\r\n\r\n"+body;
  size_t sent=0;while(sent<req.size()){if(!ready(POLLOUT))return {};auto n=::send(fd,req.data()+sent,req.size()-sent,MSG_NOSIGNAL);if(n<=0)return {};sent+=n;}
  std::string result;char buf[2048];while(true){if(!ready(POLLIN))return {};auto n=::recv(fd,buf,sizeof(buf),0);if(n==0)break;if(n<0){if(errno==EAGAIN)continue;return {};}result.append(buf,n);if(result.size()>16384)return {};}
  auto split=result.find("\r\n\r\n");if(split==std::string::npos||result.size()<12)return {};
  int code=0;if(std::sscanf(result.c_str(),"HTTP/%*s %d",&code)!=1)return {};return {code,result.substr(split+4)};
 }
};
class FileJournal:public Journal {
 std::string path_;Fd lock_;
public:
 explicit FileJournal(std::string p):path_(std::move(p)),lock_(::open((path_+".lock").c_str(),O_CREAT|O_RDWR,0600)){if(lock_<0||flock(lock_,LOCK_EX|LOCK_NB))throw std::runtime_error("journal already owned/unavailable");}
 bool load(Record& r)override{
  Fd f(::open(path_.c_str(),O_RDONLY));if(f<0)return errno==ENOENT;
  StoredRecord s{};struct stat st{};if(fstat(f,&st)||st.st_size!=sizeof(s)||::read(f,&s,sizeof(s))!=sizeof(s)||crc32(&s.record,sizeof(s.record))!=s.crc)return false;
  if(!std::memchr(s.record.operation,0,sizeof(s.record.operation))||!std::memchr(s.record.token,0,sizeof(s.record.token))||!std::memchr(s.record.device,0,sizeof(s.record.device))||!std::memchr(s.record.reservation,0,sizeof(s.record.reservation))||!std::memchr(s.record.title,0,sizeof(s.record.title)))return false;
  r=s.record;return true;
 }
 bool save(const Record& r)override{
  if(auto f=std::getenv("KIOSK_JOURNAL_FAIL_STAGE"))if(std::atoi(f)==int(r.stage))return false;
  StoredRecord s{};s.record=r;s.crc=crc32(&s.record,sizeof(s.record));Fd f(::open((path_+".tmp").c_str(),O_CREAT|O_TRUNC|O_WRONLY,0600));if(f<0||::write(f,&s,sizeof(s))!=sizeof(s)||fsync(f))return false;
  if(::rename((path_+".tmp").c_str(),path_.c_str()))return false;
  auto parent=std::filesystem::path(path_).parent_path();Fd dir(::open(parent.empty()?".":parent.c_str(),O_DIRECTORY|O_RDONLY));return dir>=0&&fsync(dir)==0;
 }
};
class HostPlatform:public Platform {
public:
 uint64_t now_us()override{return monotonic_us();}
 void random_id(char out[33])override{Fd f(::open("/dev/urandom",O_RDONLY));uint8_t bytes[16];if(f<0||::read(f,bytes,sizeof(bytes))!=sizeof(bytes))throw std::runtime_error("random source unavailable");const char* h="0123456789abcdef";for(int i=0;i<16;++i){out[i*2]=h[bytes[i]>>4];out[i*2+1]=h[bytes[i]&15];}out[32]=0;}
 void emit(const char* e,const std::string& data)override{
  std::cout<<"{\"event\":\""<<e<<"\",\"data\":"<<data<<"}"<<std::endl;
  if(std::strcmp(e,"state")==0){auto crash=std::getenv("KIOSK_CRASH_AT");if(crash){Json j(cJSON_Parse(data.c_str()));if(j.str("state")==crash)::_exit(86);}}
 }
 void indicate(const char*)override{}
};
int main(int argc,char** argv){
 try{
  std::string backend="http://127.0.0.1:9000",printer=backend,journal="host.journal",device="host-kiosk";int timeout=200;
  for(int i=1;i<argc;++i){std::string key=argv[i];if(i+1>=argc)throw std::runtime_error("missing argument");std::string value=argv[++i];if(key=="--backend")backend=value;else if(key=="--printer")printer=value;else if(key=="--journal")journal=value;else if(key=="--device")device=value;else if(key=="--timeout-ms")timeout=std::stoi(value);else throw std::runtime_error("unknown option: "+key);}
  if(timeout<10||timeout>5000)throw std::runtime_error("timeout must be 10..5000ms");
  HostPlatform platform;FileJournal storage(journal);HostHttp http(backend,timeout),ph(printer,timeout);Backend b(http);VirtualPrinterTransport pr(ph);Controller c(platform,storage,b,pr,device);Scanner parser;c.boot();
  std::string input;bool running=true,stdin_open=true;uint64_t resource_at=0;
  while(running){
   pollfd pfd{STDIN_FILENO,POLLIN,0};int result=::poll(&pfd,stdin_open?1:0,5);
   if(result>0&&(pfd.revents&(POLLIN|POLLHUP))){char buf[4096];auto n=::read(STDIN_FILENO,buf,sizeof(buf));if(n<=0)stdin_open=false;else input.append(buf,n);if(input.size()>65536)throw std::runtime_error("command buffer overflow");}
   size_t end;while((end=input.find('\n'))!=std::string::npos){
    auto line=input.substr(0,end);input.erase(0,end+1);if(!valid_json(line)){platform.emit("command_error","{\"reason\":\"INVALID_JSON\"}");continue;}
    Json j(cJSON_Parse(line.c_str()));auto cmd=j.str("cmd");bool ok=true;
    if(cmd=="scan"||cmd=="raw"){
     std::string bytes=j.str(cmd=="scan"?"data":"hex");
     if(cmd=="raw"){std::string decoded;if(bytes.size()%2)ok=false;for(size_t i=0;ok&&i<bytes.size();i+=2){unsigned x=0;char part[3]={bytes[i],bytes[i+1],0};if(!std::isxdigit(static_cast<unsigned char>(part[0]))||!std::isxdigit(static_cast<unsigned char>(part[1])))ok=false;else{std::sscanf(part,"%x",&x);decoded+=char(x);}}bytes=decoded;}
     auto source=j.num("input_us");auto source_us=(source>=0&&source<=double(platform.now_us()))?uint64_t(source):0;
     if(ok)parser.feed(reinterpret_cast<const uint8_t*>(bytes.data()),bytes.size(),platform.now_us(),[&](const Scan& s){c.enqueue(s);},source_us);
    }else if(cmd=="disconnect")parser.disconnect();
    else if(cmd=="retry")ok=c.retry();else if(cmd=="resolve_printed")ok=c.resolve_printed();else if(cmd=="quit")running=false;else if(cmd!="status")ok=false;
    Json response;response.set("id",j.num("id"));response.set("ok",ok);cJSON_AddItemToObject(response.p,"status",cJSON_Parse(c.status().c_str()));response.set("scanner_corrupt",double(parser.corrupt));platform.emit("response",response.dump());
   }
   parser.expire(platform.now_us());c.tick();
   if(!stdin_open&&c.depth()==0&&(c.state()==State::IDLE||c.state()==State::RECOVERY||c.state()==State::UNCERTAIN))break;
   if(platform.now_us()>=resource_at){struct rusage u{};getrusage(RUSAGE_SELF,&u);auto mem=mallinfo2();Json j;j.set("domain","host_native");j.set("t_us",double(platform.now_us()));j.set("rss_peak_kib",double(u.ru_maxrss));j.set("heap_allocated_bytes",double(mem.uordblks));j.set("queue_depth",double(c.depth()));platform.emit("resources",j.dump());resource_at=platform.now_us()+1000000;}
  }
  return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 2;}
}
