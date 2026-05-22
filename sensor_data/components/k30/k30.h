#ifndef K30_H
#define K30_H
#include "esp_err.h"
#include "driver/i2c.h"

#define K30_ADDR 0x68
esp_err_t k30_read_co2(i2c_port_t port, uint16_t *out_ppm);
#endif