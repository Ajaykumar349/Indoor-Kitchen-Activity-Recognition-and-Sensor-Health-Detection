idf_component_register(SRCS "wifi.c"
                    INCLUDE_DIRS "."
                    REQUIRES esp_wifi esp_event nvs_flash esp_http_client json)