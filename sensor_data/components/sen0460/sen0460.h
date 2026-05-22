#pragma once
// =============================================================
// sen0460.h  –  DFRobot SEN0460 I2C PM dust sensor for ESP-IDF
// =============================================================
#include "driver/i2c.h"

#define SEN0460_I2C_ADDR  0x19

// Particle concentration registers
#define SEN0460_REG_PM1_0   0x05
#define SEN0460_REG_PM2_5   0x07
#define SEN0460_REG_PM10    0x09

typedef struct {
    i2c_port_t i2c_port;
    uint8_t    address;
} sen0460_dev_t;

esp_err_t sen0460_init(sen0460_dev_t *dev, i2c_port_t port, uint8_t addr);

// Returns concentration in µg/m³. Returns -1 on error.
int32_t   sen0460_read_pm(sen0460_dev_t *dev, uint8_t reg);

static inline int32_t sen0460_pm1_0(sen0460_dev_t *dev)  { return sen0460_read_pm(dev, SEN0460_REG_PM1_0); }
static inline int32_t sen0460_pm2_5(sen0460_dev_t *dev)  { return sen0460_read_pm(dev, SEN0460_REG_PM2_5); }
static inline int32_t sen0460_pm10(sen0460_dev_t *dev)   { return sen0460_read_pm(dev, SEN0460_REG_PM10);  }