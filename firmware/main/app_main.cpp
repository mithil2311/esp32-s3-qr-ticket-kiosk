#include "controller.hpp"
#include "esp_platform.hpp"
#include "nvs_journal.hpp"
#include "nvs_flash.h"
#include "driver/uart.h"
#include "esp_netif.h"
#include "esp_event.h"
#include "esp_eth.h"
#include "esp_wifi.h"
#include "esp_heap_caps.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include <atomic>
using namespace kiosk;
namespace {
struct InputEvent{Scan scan;uint8_t command=0;};
QueueHandle_t input_queue,uart_events;
TaskHandle_t scanner_handle;
std::atomic<uint32_t> rx_overflow{0},bad_frames{0};
constexpr uart_port_t scanner_uart=
#if CONFIG_KIOSK_CONSOLE_INJECTION
 UART_NUM_0;
#else
 UART_NUM_1;
#endif
void scanner_task(void*){
 Scanner parser;uint8_t bytes[128];
 while(true){uart_event_t event{};bool uart_error=false;while(xQueueReceive(uart_events,&event,0)==pdTRUE){if(event.type==UART_FIFO_OVF||event.type==UART_BUFFER_FULL||event.type==UART_PARITY_ERR||event.type==UART_FRAME_ERR)uart_error=true;}
  if(uart_error){uart_flush_input(scanner_uart);parser.disconnect();++rx_overflow;}
  int n=uart_read_bytes(scanner_uart,bytes,sizeof(bytes),pdMS_TO_TICKS(20));auto now=uint64_t(esp_timer_get_time());
  if(n>0)parser.feed(bytes,n,now,[&](const Scan& s){InputEvent e{};e.scan=s;
   // Operator commands are an explicitly enabled simulation console, never QR ticket tokens.
#if CONFIG_KIOSK_EMULATION
   if(!std::strcmp(s.token,"!resolve_printed"))e.command=1;else if(!std::strcmp(s.token,"!retry"))e.command=2;
#endif
   if(xQueueSend(input_queue,&e,0)!=pdTRUE)++rx_overflow;
  });
  parser.expire(now);bad_frames=parser.corrupt;
 }
}
[[maybe_unused]] void wifi_events(void*,esp_event_base_t base,int32_t id,void*){
 if(base==WIFI_EVENT&&(id==WIFI_EVENT_STA_START||id==WIFI_EVENT_STA_DISCONNECTED))esp_wifi_connect();
}
void network_start(){
 ESP_ERROR_CHECK(esp_netif_init());ESP_ERROR_CHECK(esp_event_loop_create_default());
#if CONFIG_KIOSK_EMULATION
#if !CONFIG_ETH_USE_OPENETH
#error QEMU build requires CONFIG_ETH_USE_OPENETH
#endif
 esp_netif_config_t nc=ESP_NETIF_DEFAULT_ETH();auto netif=esp_netif_new(&nc);ESP_ERROR_CHECK(netif?ESP_OK:ESP_ERR_NO_MEM);
 eth_mac_config_t mc=ETH_MAC_DEFAULT_CONFIG();eth_phy_config_t pc=ETH_PHY_DEFAULT_CONFIG();pc.autonego_timeout_ms=100;
 auto mac=esp_eth_mac_new_openeth(&mc);auto phy=esp_eth_phy_new_dp83848(&pc);ESP_ERROR_CHECK(mac&&phy?ESP_OK:ESP_ERR_NO_MEM);esp_eth_config_t ec=ETH_DEFAULT_CONFIG(mac,phy);esp_eth_handle_t eth=nullptr;
 ESP_ERROR_CHECK(esp_eth_driver_install(&ec,&eth));auto glue=esp_eth_new_netif_glue(eth);ESP_ERROR_CHECK(esp_netif_attach(netif,glue));ESP_ERROR_CHECK(esp_eth_start(eth));
#else
 esp_netif_create_default_wifi_sta();wifi_init_config_t init=WIFI_INIT_CONFIG_DEFAULT();ESP_ERROR_CHECK(esp_wifi_init(&init));ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT,ESP_EVENT_ANY_ID,wifi_events,nullptr));wifi_config_t config{};
 std::snprintf(reinterpret_cast<char*>(config.sta.ssid),sizeof(config.sta.ssid),"%s",CONFIG_KIOSK_WIFI_SSID);std::snprintf(reinterpret_cast<char*>(config.sta.password),sizeof(config.sta.password),"%s",CONFIG_KIOSK_WIFI_PASSWORD);
 ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA,&config));ESP_ERROR_CHECK(esp_wifi_start());
#endif
}
}
extern "C" void app_main(){
 // Never erase NVS automatically: erasing an uncertain print record would permit a duplicate.
 auto init=nvs_flash_init();if(init!=ESP_OK){std::printf("NVS_INIT_FAILED: %s; operator intervention required\n",esp_err_to_name(init));return;}
 Indicator indicators;if(!indicators.init()){std::printf("INDICATOR_GPIO_INIT_FAILED\n");return;}
 network_start();
 input_queue=xQueueCreate(8,sizeof(InputEvent));ESP_ERROR_CHECK(input_queue?ESP_OK:ESP_ERR_NO_MEM);
 uart_config_t uart{};uart.baud_rate=CONFIG_KIOSK_SCANNER_BAUD;uart.data_bits=UART_DATA_8_BITS;uart.parity=UART_PARITY_DISABLE;uart.stop_bits=UART_STOP_BITS_1;uart.flow_ctrl=UART_HW_FLOWCTRL_DISABLE;uart.source_clk=UART_SCLK_DEFAULT;
 ESP_ERROR_CHECK(uart_param_config(scanner_uart,&uart));
#if !CONFIG_KIOSK_CONSOLE_INJECTION
 ESP_ERROR_CHECK(uart_set_pin(scanner_uart,CONFIG_KIOSK_SCANNER_TX,CONFIG_KIOSK_SCANNER_RX,UART_PIN_NO_CHANGE,UART_PIN_NO_CHANGE));
#endif
 ESP_ERROR_CHECK(uart_driver_install(scanner_uart,2048,0,20,&uart_events,0));
 ESP_ERROR_CHECK(xTaskCreate(scanner_task,"scanner",4096,nullptr,5,&scanner_handle)==pdPASS?ESP_OK:ESP_ERR_NO_MEM);
 EspPlatform p(indicators);NvsJournal journal;EspHttp http(CONFIG_KIOSK_BACKEND_URL),printer_http(CONFIG_KIOSK_PRINTER_URL);Backend backend(http);
#if CONFIG_KIOSK_EMULATION
 VirtualPrinterTransport printer(printer_http);
#else
 UnconfiguredHardwarePrinter printer;
#endif
 Controller controller(p,journal,backend,printer,CONFIG_KIOSK_DEVICE_ID);controller.boot();uint64_t sample=0;
 while(true){InputEvent e{};while(xQueueReceive(input_queue,&e,0)==pdTRUE){if(e.command==1)controller.resolve_printed();else if(e.command==2)controller.retry();else controller.enqueue(e.scan);}
  controller.tick();auto now=uint64_t(esp_timer_get_time());indicators.tick(now);
  if(now>=sample){Json j;j.set("domain",
#if CONFIG_KIOSK_EMULATION
  "qemu_xtensa_firmware"
#else
  "esp32s3_hardware"
#endif
  );j.set("t_us",double(now));j.set("heap_free_bytes",double(esp_get_free_heap_size()));j.set("heap_min_bytes",double(esp_get_minimum_free_heap_size()));j.set("controller_stack_hwm_bytes",double(uxTaskGetStackHighWaterMark(nullptr)));j.set("scanner_stack_hwm_bytes",double(uxTaskGetStackHighWaterMark(scanner_handle)));j.set("rtos_queue_depth",double(uxQueueMessagesWaiting(input_queue)));j.set("controller_queue_depth",double(controller.depth()));j.set("rtos_queue_overflow",double(rx_overflow.load()));j.set("scanner_corrupt",double(bad_frames.load()));j.set("failures",double(controller.failures));p.emit("resources",j.dump());sample=now+1000000;}
  vTaskDelay(pdMS_TO_TICKS(5));
 }
}
