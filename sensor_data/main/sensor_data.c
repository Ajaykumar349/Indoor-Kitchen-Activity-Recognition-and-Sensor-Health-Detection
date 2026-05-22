// =============================================================
// Kitchen AI Receiver - WebSocket Edition
// ESP32-S3 + Local TB600B Sensors + Streamlit WebSocket
// =============================================================

#include <stdio.h>
#include <string.h>
#include <time.h>
#include <sys/time.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"

#include "esp_wifi.h"
#include "esp_system.h"
#include "esp_log.h"
#include "esp_now.h"
#include "esp_netif.h"
#include "esp_event.h"
#include "nvs_flash.h"

#include "driver/i2c.h"
#include "driver/uart.h"

#include "esp_websocket_client.h"

// Sensors
#include "k30.h"
#include "tb600b.h"
#include "ssd1306.h"
#include "wifi.h"
#include "sen0460.h"

static const char *TAG = "KITCHEN_AI";

// =============================================================
// I2C CONFIG
// =============================================================

#define I2C_BUS_SHARED I2C_NUM_0
#define SHARED_SDA     4
#define SHARED_SCL     5

#define I2C_BUS_K30    I2C_NUM_1
#define K30_SDA        10
#define K30_SCL        46

// =============================================================
// UART CONFIG
// =============================================================

// CO SENSOR
#define CO_UART        UART_NUM_2
#define CO_TX          17
#define CO_RX          9

// VOC SENSOR
// IMPORTANT: DO NOT USE UART0 (USB Serial Logging)
#define VOC_UART       UART_NUM_1
#define VOC_TX         16
#define VOC_RX         18

// =============================================================
// WEBSOCKET SERVER
// =============================================================

#define WS_SERVER_URI "ws://10.139.71.194:5000/ws"

// =============================================================
// SENSOR DATA
// =============================================================

typedef struct {
    uint16_t co2;

    uint16_t pm1;
    uint16_t pm25;
    uint16_t pm10;

    float co;
    float voc;
    float temperature;
    float humidity;

    struct tm timeinfo;

    bool co2_ok;
    bool pm_ok;
    bool co_ok;
    bool voc_ok;

} sensor_data_t;

static sensor_data_t g_data;
static SemaphoreHandle_t g_mutex;
static sen0460_dev_t sen0460;

// Local Driver Handles for TB600B Sensors
static tb600b_handle_t co_handle;
static tb600b_handle_t voc_handle;

// =============================================================
// WEBSOCKET CLIENT
// =============================================================

static esp_websocket_client_handle_t ws_client = NULL;

// =============================================================
// WEBSOCKET EVENT HANDLER
// =============================================================

static void websocket_event_handler(
    void *handler_args,
    esp_event_base_t base,
    int32_t event_id,
    void *event_data)
{
    esp_websocket_event_data_t *data =
        (esp_websocket_event_data_t *)event_data;

    switch (event_id)
    {
        case WEBSOCKET_EVENT_CONNECTED:
            ESP_LOGI(TAG, "WebSocket Connected");
            break;

        case WEBSOCKET_EVENT_DISCONNECTED:
            ESP_LOGW(TAG, "WebSocket Disconnected");
            break;

        case WEBSOCKET_EVENT_DATA:
            ESP_LOGI(TAG,
                     "WS RX: %.*s",
                     data->data_len,
                     (char *)data->data_ptr);
            break;

        case WEBSOCKET_EVENT_ERROR:
            ESP_LOGE(TAG, "WebSocket Error");
            break;

        default:
            break;
    }
}

// =============================================================
// SEND JSON TO USB (PRINT ALL PM CHANNELS)
// =============================================================

static void print_json_debug(void)
{
    char time_str[32];

    strftime(time_str,
             sizeof(time_str),
             "%H:%M:%S",
             &g_data.timeinfo);

    char json[512];

    snprintf(json,
             sizeof(json),
             "{\"time\":\"%s\","
             "\"co2\":%u,"
             "\"pm1\":%u,"
             "\"pm25\":%u,"
             "\"pm10\":%u,"
             "\"co\":%.2f,"
             "\"voc\":%.1f,"
             "\"temp\":%.2f,"
             "\"hum\":%.2f}",
             time_str,
             g_data.co2,
             g_data.pm1,
             g_data.pm25,
             g_data.pm10,
             g_data.co,
             g_data.voc,
             g_data.temperature,
             g_data.humidity);

    printf("%s\n", json);
    fflush(stdout);
}

// =============================================================
// SEND DATA VIA WEBSOCKET (PRINT ALL PM CHANNELS)
// =============================================================

static void send_data_via_websocket(void)
{
    if (!esp_websocket_client_is_connected(ws_client))
    {
        ESP_LOGW(TAG, "WebSocket not connected");
        return;
    }

    char time_str[32];

    strftime(time_str,
             sizeof(time_str),
             "%H:%M:%S",
             &g_data.timeinfo);

    char json[512];

    snprintf(json,
             sizeof(json),
             "{\"time\":\"%s\","
             "\"co2\":%u,"
             "\"pm1\":%u,"
             "\"pm25\":%u,"
             "\"pm10\":%u,"
             "\"co\":%.2f,"
             "\"voc\":%.1f,"
             "\"temp\":%.2f,\"hum\":%.2f}",
             time_str,
             g_data.co2,
             g_data.pm1,
             g_data.pm25,
             g_data.pm10,
             g_data.co,
             g_data.voc,
             g_data.temperature,
             g_data.humidity);
    
    int ret = esp_websocket_client_send_text(
        ws_client,
        json,
        strlen(json),
        portMAX_DELAY);

    printf("SEND RESULT: %d\n", ret); 

    ESP_LOGI(TAG, "WS Sent: %s", json);
}

// =============================================================
// I2C INIT
// =============================================================

static void i2c_init(void)
{
    i2c_config_t shared_bus = {
        .mode = I2C_MODE_MASTER,
        .sda_io_num = SHARED_SDA,
        .scl_io_num = SHARED_SCL,
        .sda_pullup_en = GPIO_PULLUP_ENABLE,
        .scl_pullup_en = GPIO_PULLUP_ENABLE,
        .master.clk_speed = 100000
    };

    i2c_param_config(I2C_BUS_SHARED, &shared_bus);
    i2c_driver_install(I2C_BUS_SHARED, I2C_MODE_MASTER, 0, 0, 0);

    i2c_config_t k30_bus = {
        .mode = I2C_MODE_MASTER,
        .sda_io_num = K30_SDA,
        .scl_io_num = K30_SCL,
        .sda_pullup_en = GPIO_PULLUP_ENABLE,
        .scl_pullup_en = GPIO_PULLUP_ENABLE,
        .master.clk_speed = 100000
    };

    i2c_param_config(I2C_BUS_K30, &k30_bus);
    i2c_driver_install(I2C_BUS_K30, I2C_MODE_MASTER, 0, 0, 0);
}

// =============================================================
// UART INIT
// =============================================================

static void uart_init_custom(void)
{
    uart_config_t cfg = {
        .baud_rate = 9600,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE
    };

    // CO SENSOR UART
    uart_param_config(CO_UART, &cfg);
    uart_set_pin(CO_UART, CO_TX, CO_RX, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
    uart_driver_install(CO_UART, 512, 0, 0, NULL, 0);

    // VOC SENSOR UART
    uart_param_config(VOC_UART, &cfg);
    uart_set_pin(VOC_UART, VOC_TX, VOC_RX, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
    uart_driver_install(VOC_UART, 512, 0, 0, NULL, 0);
}

// =============================================================
// SENSOR TASK
// =============================================================

static void task_update(void *arg)
{
    oled_init(I2C_BUS_SHARED);

    ESP_ERROR_CHECK(
        sen0460_init(
            &sen0460,
            I2C_BUS_SHARED,
            SEN0460_I2C_ADDR));

    // Initialize Local TB600B Driver Modules
    ESP_ERROR_CHECK(tb600_init(&co_handle, CO_UART, TB600B_TYPE_CO_ONLY));
    ESP_ERROR_CHECK(tb600_init(&voc_handle, VOC_UART, TB600B_TYPE_VOC_TEMP_HUMID));

    while (1)
    {
        sensor_data_t s = {0};

        // ================= CO2 =================

        s.co2_ok = (k30_read_co2(I2C_BUS_K30, &s.co2) == ESP_OK);
        vTaskDelay(pdMS_TO_TICKS(200));

        // ================= PM (PM1, PM2.5, PM10) =================

        int32_t pm1 = sen0460_pm1_0(&sen0460);
        int32_t pm25 = sen0460_pm2_5(&sen0460);
        int32_t pm10 = sen0460_pm10(&sen0460);

        if (pm1 != -1 && pm25 != -1 && pm10 != -1)
        {
            s.pm1 = pm1;
            s.pm25 = pm25;
            s.pm10 = pm10;
            s.pm_ok = true;
        }

        // ================= CO SENSOR =================

        s.co_ok = (tb600_read_co(&co_handle, &s.co) == ESP_OK);
        vTaskDelay(pdMS_TO_TICKS(300));

        // ================= VOC + TEMP + HUMID SENSOR =================

        s.voc_ok = (tb600_read_all(&voc_handle, &s.voc, &s.temperature, &s.humidity) == ESP_OK);
        if (!s.voc_ok) {
            ESP_LOGE(TAG, "Multi-parameter unified payload parse failed over UART port %d", VOC_UART);
        }

        // ================= TIME =================

        time_t now;
        time(&now);
        localtime_r(&now, &s.timeinfo);

        // ================= SAVE =================

        xSemaphoreTake(g_mutex, portMAX_DELAY);
        g_data = s;
        xSemaphoreGive(g_mutex);

        // ================= SERIAL (PRINT PM1, PM2.5, PM10) =================

        printf("\n==== KITCHEN AI LOCAL READINGS ====\n");
        printf("CO2: %u ppm | PM1: %u | PM2.5: %u | PM10: %u\n", s.co2, s.pm1, s.pm25, s.pm10);
        printf("CO: %.2f ppm | VOC: %.1f ppm\n", s.co, s.voc);
        printf("Temp: %.2f °C | Hum: %.2f %%\n", s.temperature, s.humidity);

        // ================= OLED (DISPLAYING ALL PM VALS) =================

        oled_clear();
        char b[40];

        snprintf(b, sizeof(b), "CO2:%u PM2.5:%u", s.co2, s.pm25);
        oled_draw_string(0, 0, b);

        snprintf(b, sizeof(b), "PM1:%u PM10:%u", s.pm1, s.pm10);
        oled_draw_string(0, 2, b);

        snprintf(b, sizeof(b), "CO:%.1f VOC:%.0f", s.co, s.voc);
        oled_draw_string(0, 4, b);

        snprintf(b, sizeof(b), "T:%.1f H:%.0f", s.temperature, s.humidity);
        oled_draw_string(0, 6, b);

        oled_flush(I2C_BUS_SHARED);

        // ================= DEBUG & TRANSMIT =================

        print_json_debug();
        send_data_via_websocket();

        vTaskDelay(pdMS_TO_TICKS(5000));
    }
}

// =============================================================
// APP MAIN
// =============================================================

void app_main(void)
{
    g_mutex = xSemaphoreCreateMutex();

    // ================= INIT =================

    i2c_init();
    uart_init_custom();

    // ================= WIFI =================
   
    wifi_init_sta();

    // ================= ESPNOW =================

    ESP_ERROR_CHECK(esp_now_init());

    // ================= WEBSOCKET =================

    esp_websocket_client_config_t ws_cfg = {
        .uri = WS_SERVER_URI,
    };

    ws_client = esp_websocket_client_init(&ws_cfg);

    esp_websocket_register_events(
        ws_client,
        WEBSOCKET_EVENT_ANY,
        websocket_event_handler,
        NULL);

    esp_websocket_client_start(ws_client);
    ESP_LOGI(TAG, "WebSocket Started");

    // ================= TASK =================

    xTaskCreate(
        task_update,
        "task_update",
        8192,
        NULL,
        5,
        NULL);
}