#include "tb600b.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "TB600B";

// =============================================================
// OFFICIAL 13-BYTE PROTOCOL REGISTER COMMANDS (NO LED)
// =============================================================
static const uint8_t CMD_PASSIVE[] = {0xFF, 0x01, 0x78, 0x41, 0x00, 0x00, 0x00, 0x00, 0x46};
static const uint8_t CMD_READ[]    = {0xFF, 0x01, 0x87, 0x00, 0x00, 0x00, 0x00, 0x00, 0x78};

/**
 * @brief Ported Checksum calculation algorithm for 13-byte payload frames
 * Sums data bytes from index 1 to 11, returns bitwise negated byte + 1.
 */
static uint8_t tb600_calculate_checksum(const uint8_t *buf) {
    uint8_t sum = 0;
    for (int i = 1; i < 12; i++) {
        sum += buf[i];
    }
    return (uint8_t)(~sum + 1);
}

/**
 * @brief Initialize TB600B sensor handle instance
 */
esp_err_t tb600_init(tb600b_handle_t *handle, uart_port_t port, tb600b_sensor_type_t sensor_type) {
    if (handle == NULL) {
        ESP_LOGE(TAG, "Initialization failed: handle context cannot be NULL");
        return ESP_FAIL;
    }
    
    handle->uart_port = port;
    handle->sensor_type = sensor_type;
    
    // Force the hardware sub-module to drop into passive mode instantly at startup
    uart_flush_input(port);
    uart_write_bytes(port, (const char *)CMD_PASSIVE, 9);
    vTaskDelay(pdMS_TO_TICKS(100));
    
    ESP_LOGI(TAG, "Initialized %s on UART port %d in PASSIVE Mode",
             tb600_get_sensor_type_str(handle), port);
    
    return ESP_OK;
}

/**
 * @brief Efficient Unified 4-Parameter Single-Frame Read & Compensation Engine
 */
esp_err_t tb600_read_all(tb600b_handle_t *handle, float *gas_val, float *temp_val, float *humid_val) {
    if (handle == NULL || gas_val == NULL || temp_val == NULL || humid_val == NULL) {
        return ESP_FAIL;
    }
    
    uint8_t buf[13] = {0};
    uart_port_t port = handle->uart_port;
    
    // Clean old hanging data bytes from input buffer
    uart_flush_input(port);
    
    // 1. Direct Request for the 13-byte telemetry frame data payload
    uart_write_bytes(port, (const char *)CMD_READ, 9);
    
    // 2. Collect exactly 13 data bytes from UART ring buffer queue
    int bytes_read = uart_read_bytes(port, buf, 13, pdMS_TO_TICKS(1000));
    
    if (bytes_read != 13) {
        ESP_LOGE(TAG, "UART Port %d timeout error: Expected 13 bytes, received %d", port, bytes_read);
        return ESP_FAIL;
    }
    
    // 3. Structure confirmation check
    if (buf[0] != 0xFF || buf[1] != 0x87) {
        ESP_LOGE(TAG, "UART Port %d invalid frame headers: [0x%02X, 0x%02X]", port, buf[0], buf[1]);
        return ESP_FAIL;
    }
    
    // 4. Validate computed checksum vs frame checksum byte
    if (tb600_calculate_checksum(buf) != buf[12]) {
        ESP_LOGE(TAG, "UART Port %d payload data corrupted: Checksum mismatch", port);
        return ESP_ERR_INVALID_CRC;
    }
    
    // 5. Extract raw PPB gas values (Bytes 6 & 7)
    uint16_t raw_ppb = (uint16_t)((buf[6] << 8) | buf[7]);
    
    // 6. Extract raw high-resolution ambient values (Bytes 8 through 11)
    int16_t raw_temp = (int16_t)((buf[8] << 8) | buf[9]);
    uint16_t raw_humid = (uint16_t)((buf[10] << 8) | buf[11]);
    
    // 7. Process exact floating point resolution parsing (/ 100.0)
    float parsed_temp = (float)raw_temp / 100.0f;
    float parsed_humid = (float)raw_humid / 100.0f;
    
    // 8. Sensor physical sanity parameters filtering block
    if (parsed_temp < -40.0f || parsed_temp > 85.0f || parsed_humid > 100.0f) {
        ESP_LOGW(TAG, "Hardware boundary overflow rejected. Temp: %.2f C, Hum: %.2f %%", parsed_temp, parsed_humid);
        return ESP_ERR_INVALID_STATE;
    }
    
    // 9. Run onboard cross-channel calibration compensation loops
    float compensated_gas = (float)raw_ppb;
    
    // Temperature Curve Compensation logic: +/-0.3% per deg C away from 26C baseline
    compensated_gas *= (1.0f + 0.003f * (parsed_temp - 26.0f));
    
    // Humidity Curve Compensation logic: +/-0.15% per %RH away from 55% baseline
    compensated_gas *= (1.0f + 0.0015f * (parsed_humid - 55.0f));
    
    // Convert PPB to PPM for standard main.c processing
    //float final_ppm = compensated_gas / 1000.0f;
    
    // Assign parsed outputs out to referencing memory spaces
    *gas_val   = compensated_gas;
    *temp_val  = parsed_temp;
    *humid_val = parsed_humid;
    
    ESP_LOGI(TAG, "Port %d Data Sync -> Gas: %.2f ppm | Temp: %.2f C | Hum: %.2f %%",
             port, *gas_val, *temp_val, *humid_val);
             
    return ESP_OK;
}

/**
 * @brief Standalone Read wrappers modified to route through the unified 13-Byte parsing engine
 */
esp_err_t tb600_read_voc(tb600b_handle_t *handle, float *out_val) {
    float dummy_t, dummy_h;
    return tb600_read_all(handle, out_val, &dummy_t, &dummy_h);
}

esp_err_t tb600_read_co(tb600b_handle_t *handle, float *out_val) {
    float dummy_t, dummy_h;
    return tb600_read_all(handle, out_val, &dummy_t, &dummy_h);
}

esp_err_t tb600_read_temp(tb600b_handle_t *handle, float *out_val) {
    float dummy_g, dummy_h;
    return tb600_read_all(handle, &dummy_g, out_val, &dummy_h);
}

esp_err_t tb600_read_humidity(tb600b_handle_t *handle, float *out_val) {
    float dummy_g, dummy_t;
    return tb600_read_all(handle, &dummy_g, &dummy_t, out_val);
}

/**
 * @brief Get sensor type as string
 */
const char* tb600_get_sensor_type_str(tb600b_handle_t *handle) {
    if (handle == NULL) {
        return "INVALID";
    }
    
    switch (handle->sensor_type) {
        case TB600B_TYPE_VOC_TEMP_HUMID:
            return "VOC/TEMP/HUMIDITY";
        case TB600B_TYPE_CO_ONLY:
            return "CO_ONLY";
        default:
            return "UNKNOWN";
    }
}