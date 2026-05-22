#include "wifi.h"
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"

#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "nvs_flash.h"
#include "esp_netif.h"

#define WIFI_SSID "Ajay"
#define WIFI_PASS "7248467734"

static const char *TAG = "WIFI_COMP";

/* =========================================================
 * EVENT GROUP
 * ========================================================= */
static EventGroupHandle_t s_wifi_event_group;

#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAIL_BIT      BIT1

static int s_retry_num = 0;

#define EXAMPLE_ESP_MAXIMUM_RETRY 10

/* =========================================================
 * WIFI EVENT HANDLER
 * ========================================================= */
static void wifi_event_handler(void *arg,
                               esp_event_base_t event_base,
                               int32_t event_id,
                               void *event_data)
{
    /* ---------------- WIFI START ---------------- */
    if (event_base == WIFI_EVENT &&
        event_id == WIFI_EVENT_STA_START)
    {
        ESP_LOGI(TAG, "WiFi started, connecting...");
        esp_wifi_connect();
    }

    /* ---------------- WIFI DISCONNECTED ---------------- */
    else if (event_base == WIFI_EVENT &&
             event_id == WIFI_EVENT_STA_DISCONNECTED)
    {
        wifi_event_sta_disconnected_t *disconn =
            (wifi_event_sta_disconnected_t *)event_data;

        ESP_LOGW(TAG,
                 "Disconnected! reason=%d",
                 disconn->reason);

        if (s_retry_num < EXAMPLE_ESP_MAXIMUM_RETRY)
        {
            esp_wifi_connect();

            s_retry_num++;

            ESP_LOGI(TAG,
                     "Retrying connection (%d/%d)",
                     s_retry_num,
                     EXAMPLE_ESP_MAXIMUM_RETRY);
        }
        else
        {
            xEventGroupSetBits(s_wifi_event_group,
                               WIFI_FAIL_BIT);

            ESP_LOGE(TAG, "Max retries reached");
        }
    }

    /* ---------------- GOT IP ---------------- */
    else if (event_base == IP_EVENT &&
             event_id == IP_EVENT_STA_GOT_IP)
    {
        ip_event_got_ip_t *event =
            (ip_event_got_ip_t *)event_data;

        ESP_LOGI(TAG,
                 "Got IP: " IPSTR,
                 IP2STR(&event->ip_info.ip));

        s_retry_num = 0;

        xEventGroupSetBits(s_wifi_event_group,
                           WIFI_CONNECTED_BIT);
    }
}

/* =========================================================
 * WIFI INIT
 * ========================================================= */
void wifi_init_sta(void)
{
    esp_err_t ret;

    /* ---------------- CREATE EVENT GROUP ---------------- */
    s_wifi_event_group = xEventGroupCreate();

    /* ---------------- NVS INIT ---------------- */
    ret = nvs_flash_init();

    if (ret == ESP_ERR_NVS_NO_FREE_PAGES ||
        ret == ESP_ERR_NVS_NEW_VERSION_FOUND)
    {
        ESP_ERROR_CHECK(nvs_flash_erase());

        ret = nvs_flash_init();
    }

    ESP_ERROR_CHECK(ret);

    /* ---------------- NETWORK STACK ---------------- */
    ESP_ERROR_CHECK(esp_netif_init());

    /* Create default event loop only once */
    ret = esp_event_loop_create_default();

    if (ret != ESP_ERR_INVALID_STATE)
    {
        ESP_ERROR_CHECK(ret);
    }

    /* Create WiFi station */
    esp_netif_create_default_wifi_sta();

    /* ---------------- WIFI INIT ---------------- */
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();

    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    /* ---------------- COUNTRY CONFIG ---------------- */
    wifi_country_t country = {
        .cc = "IN",
        .schan = 1,
        .nchan = 13,
        .policy = WIFI_COUNTRY_POLICY_AUTO
    };

    ESP_ERROR_CHECK(esp_wifi_set_country(&country));

    /* ---------------- REGISTER EVENTS ---------------- */
    esp_event_handler_instance_t instance_any_id;
    esp_event_handler_instance_t instance_got_ip;

    ESP_ERROR_CHECK(
        esp_event_handler_instance_register(
            WIFI_EVENT,
            ESP_EVENT_ANY_ID,
            &wifi_event_handler,
            NULL,
            &instance_any_id));

    ESP_ERROR_CHECK(
        esp_event_handler_instance_register(
            IP_EVENT,
            IP_EVENT_STA_GOT_IP,
            &wifi_event_handler,
            NULL,
            &instance_got_ip));

    /* ---------------- WIFI CONFIG ---------------- */
    wifi_config_t wifi_config = {
        .sta = {
            .ssid = WIFI_SSID,
            .password = WIFI_PASS,

            /* Better scanning */
            .scan_method = WIFI_ALL_CHANNEL_SCAN,

            /* Connect strongest AP */
            .sort_method = WIFI_CONNECT_AP_BY_SIGNAL,

            /* Allow WPA/WPA2/WPA3 */
            .threshold.authmode = WIFI_AUTH_OPEN,

            /* Protected management frames */
            .pmf_cfg = {
                .capable = true,
                .required = false
            },
            
        },
    };

    /* ---------------- WIFI MODE ---------------- */
    ESP_ERROR_CHECK(
        esp_wifi_set_mode(WIFI_MODE_STA));

    /* RAM storage */
    ESP_ERROR_CHECK(
        esp_wifi_set_storage(WIFI_STORAGE_RAM));

    /* Apply config */
    ESP_ERROR_CHECK(
        esp_wifi_set_config(WIFI_IF_STA,
                            &wifi_config));

    /* Start WiFi */
    ESP_ERROR_CHECK(
        esp_wifi_start());

    /* ---------------- SET MAX TX POWER ---------------- */
    // Configured in steps of 0.25 dBm: 15 dBm * 4 = 60
    int8_t tx_power_val = 15 * 4;
    esp_err_t power_err = esp_wifi_set_max_tx_power(tx_power_val);
    if (power_err == ESP_OK) {
        ESP_LOGI(TAG, "Wi-Fi Max TX Power successfully limited to 15 dBm (API Value: %d)", tx_power_val);
    } else {
        ESP_LOGE(TAG, "Failed to apply Wi-Fi TX Power restrictions: %s", esp_err_to_name(power_err));
    }

    /* Disable power save for stable ESP-NOW + HTTP */
    ESP_ERROR_CHECK(
        esp_wifi_set_ps(WIFI_PS_NONE));

    ESP_LOGI(TAG, "wifi_init_sta finished");

    /* ---------------- WAIT FOR CONNECTION ---------------- */
    EventBits_t bits = xEventGroupWaitBits(
        s_wifi_event_group,
        WIFI_CONNECTED_BIT | WIFI_FAIL_BIT,
        pdFALSE,
        pdFALSE,
        pdMS_TO_TICKS(20000));

    /* ---------------- RESULT ---------------- */
    if (bits & WIFI_CONNECTED_BIT)
    {
        ESP_LOGI(TAG,
                 "Connected to AP: %s",
                 WIFI_SSID);
    }
    else if (bits & WIFI_FAIL_BIT)
    {
        ESP_LOGE(TAG,
                 "Failed to connect to SSID: %s",
                 WIFI_SSID);
    }
    else
    {
        ESP_LOGE(TAG,
                 "Connection timeout");
    }
}