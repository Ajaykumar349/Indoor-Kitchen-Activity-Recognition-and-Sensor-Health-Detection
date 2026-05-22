// =============================================================
// sen0460.c  –  DFRobot SEN0460 I2C PM dust sensor for ESP-IDF
// =============================================================
#include "sen0460.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "SEN0460";
#define I2C_TIMEOUT_MS 100

esp_err_t sen0460_init(sen0460_dev_t *dev, i2c_port_t port, uint8_t addr)
{
    dev->i2c_port = port;
    dev->address  = addr;

    // awake command: write [0x01, 0x02] to device using legacy API
    uint8_t wake_cmd[2] = {0x01, 0x02};
    
    i2c_cmd_handle_t cmd = i2c_cmd_link_create();
    i2c_master_start(cmd);
    i2c_master_write_byte(cmd, (dev->address << 1) | I2C_MASTER_WRITE, true);
    i2c_master_write(cmd, wake_cmd, 2, true);
    i2c_master_stop(cmd);
    esp_err_t ret = i2c_master_cmd_begin(dev->i2c_port, cmd, pdMS_TO_TICKS(I2C_TIMEOUT_MS));
    i2c_cmd_link_delete(cmd);

    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "Wake command failed: %s", esp_err_to_name(ret));
    }
    
    vTaskDelay(pdMS_TO_TICKS(2000));
    ESP_LOGI(TAG, "SEN0460 initialised at addr 0x%02X", addr);
    return ESP_OK;
}

int32_t sen0460_read_pm(sen0460_dev_t *dev, uint8_t reg)
{
    uint8_t buf[2];
    
    i2c_cmd_handle_t cmd = i2c_cmd_link_create();
    i2c_master_start(cmd);
    
    // Write register address
    i2c_master_write_byte(cmd, (dev->address << 1) | I2C_MASTER_WRITE, true);
    i2c_master_write_byte(cmd, reg, true);
    
    // Repeated start for reading
    i2c_master_start(cmd);
    i2c_master_write_byte(cmd, (dev->address << 1) | I2C_MASTER_READ, true);
    i2c_master_read_byte(cmd, &buf[0], I2C_MASTER_ACK);
    i2c_master_read_byte(cmd, &buf[1], I2C_MASTER_NACK);
    i2c_master_stop(cmd);
    
    esp_err_t ret = i2c_master_cmd_begin(dev->i2c_port, cmd, pdMS_TO_TICKS(I2C_TIMEOUT_MS));
    i2c_cmd_link_delete(cmd);

    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Read failed for reg 0x%02X: %s", reg, esp_err_to_name(ret));
        return -1;
    }
    
    // Combine the two bytes into a 16-bit integer
    return (int32_t)(((uint16_t)buf[0] << 8) | buf[1]);
}