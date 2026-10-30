idf_component_register(SRCS "app_main.cpp" INCLUDE_DIRS "."
 REQUIRES ticket_controller qr_scanner backend_client printer transaction_journal indicators platform_hal
 esp_eth esp_netif esp_event esp_wifi esp_driver_uart esp_timer esp_system esp_hw_support)
