#ifndef SSD1306_H
#define SSD1306_H

#include "driver/i2c.h"
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t oled_init(i2c_port_t port);
void oled_clear(void);
void oled_draw_string(int x, int y, const char *str);
void oled_flush(i2c_port_t port);

#ifdef __cplusplus
}
#endif

#endif // SSD1306_H