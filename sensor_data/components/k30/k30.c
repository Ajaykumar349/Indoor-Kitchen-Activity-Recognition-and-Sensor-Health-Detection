#include "k30.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

esp_err_t k30_read_co2(i2c_port_t port, uint16_t *out_ppm) {
    static const uint8_t cmd[] = {0x22, 0x00, 0x08, 0x2A};
    uint8_t resp[4] = {0};

    esp_err_t r = i2c_master_write_to_device(port, K30_ADDR, cmd, sizeof(cmd), pdMS_TO_TICKS(100));
    if (r != ESP_OK) return r;

    vTaskDelay(pdMS_TO_TICKS(20));

    r = i2c_master_read_from_device(port, K30_ADDR, resp, sizeof(resp), pdMS_TO_TICKS(100));
    if (r != ESP_OK) return r;

    uint8_t chk = (uint8_t)((resp[0] + resp[1] + resp[2]) & 0xFF);
    if (chk != resp[3]) return ESP_ERR_INVALID_CRC;

    *out_ppm = ((uint16_t)resp[1] << 8) | resp[2];
    return ESP_OK;
}