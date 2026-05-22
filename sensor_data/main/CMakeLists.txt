idf_component_register(
    SRCS "sensor_data.c"
    INCLUDE_DIRS "."
    REQUIRES
        k30
        sen0460
        ssd1306
        esp_websocket_client
        tb600b
        wifi
        esp_wifi
        esp_event
        nvs_flash
        esp_netif
        esp_http_client
        driver
)