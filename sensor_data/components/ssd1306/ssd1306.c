#include "ssd1306.h"
#include <string.h>
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "SSD1306";

// Standard I2C address for 0.96" OLED is 0x3C
#ifndef OLED_ADDR
#define OLED_ADDR 0x3C 
#endif

static uint8_t oled_buf[8][128];

static esp_err_t oled_write_cmd(i2c_port_t port, uint8_t cmd) {
    uint8_t buf[2] = {0x00, cmd};
    return i2c_master_write_to_device(port, OLED_ADDR, buf, 2, pdMS_TO_TICKS(100));
}

esp_err_t oled_init(i2c_port_t port) {
    const uint8_t init_seq[] = {
        0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 
        0x40, // Display Start Line (0)
        0x8D, 0x14, 0x20, 0x00, 0xA1, 0xC8, 0xDA, 0x12, 
        0x81, 0xCF, 0xD9, 0xF1, 0xDB, 0x40, 0xA4, 0xA6, 0xAF
    };

    vTaskDelay(pdMS_TO_TICKS(100));
    for (size_t i = 0; i < sizeof(init_seq); i++) {
        esp_err_t r = oled_write_cmd(port, init_seq[i]);
        if (r != ESP_OK) return r;
    }
    oled_clear();
    return ESP_OK;
}

void oled_clear(void) {
    memset(oled_buf, 0, sizeof(oled_buf));
}

void oled_draw_string(int col, int page, const char *str) {
    // Uses the internal font5x7 mapping
    while (*str && col < 128) {
        // ... (Refer to your existing oled_draw_char implementation) ...
        str++;
        col += 6;
    }
}


void oled_flush(i2c_port_t port) {
    oled_write_cmd(port, 0x21); oled_write_cmd(port, 0); oled_write_cmd(port, 127);
    oled_write_cmd(port, 0x22); oled_write_cmd(port, 0); oled_write_cmd(port, 7);

    for (int p = 0; p < 8; p++) {
        uint8_t buf[129];
        buf[0] = 0x40; // Data mode
        memcpy(&buf[1], oled_buf[p], 128);
        i2c_master_write_to_device(port, OLED_ADDR, buf, sizeof(buf), pdMS_TO_TICKS(200));
    }
}