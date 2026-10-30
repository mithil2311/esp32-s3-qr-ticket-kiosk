#pragma once
#include "driver/gpio.h"
#include "sdkconfig.h"
#include <cstring>
namespace kiosk {
class Indicator {
 bool enabled_=false;int64_t buzzer_off_=0;
public:
 bool init(){
#if !CONFIG_KIOSK_EMULATION
  gpio_config_t c{};c.pin_bit_mask=(1ULL<<CONFIG_KIOSK_GREEN_GPIO)|(1ULL<<CONFIG_KIOSK_RED_GPIO)|(1ULL<<CONFIG_KIOSK_BUZZER_GPIO);c.mode=GPIO_MODE_OUTPUT;
  enabled_=gpio_config(&c)==ESP_OK;return enabled_;
#else
  return true;
#endif
 }
 void state(const char* s,int64_t now){if(!enabled_)return;bool success=!std::strcmp(s,"SUCCESS");bool error=!std::strcmp(s,"UNCERTAIN")||!std::strcmp(s,"RECOVERY")||!std::strcmp(s,"REJECTED");gpio_set_level(gpio_num_t(CONFIG_KIOSK_GREEN_GPIO),success||!std::strcmp(s,"IDLE"));gpio_set_level(gpio_num_t(CONFIG_KIOSK_RED_GPIO),error);gpio_set_level(gpio_num_t(CONFIG_KIOSK_BUZZER_GPIO),success||error);buzzer_off_=now+100000;}
 void tick(int64_t now){if(enabled_&&now>=buzzer_off_)gpio_set_level(gpio_num_t(CONFIG_KIOSK_BUZZER_GPIO),0);}
};
}
