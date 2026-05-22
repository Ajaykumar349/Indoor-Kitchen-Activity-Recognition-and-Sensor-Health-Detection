#ifndef TB600B_H
#define TB600B_H

#include "driver/uart.h"
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

// Sensor type definitions
typedef enum {
    TB600B_TYPE_VOC_TEMP_HUMID = 0,  // Sensor 1: reads VOC, Temperature, Humidity
    TB600B_TYPE_CO_ONLY = 1           // Sensor 2: reads only CO
} tb600b_sensor_type_t;

// Sensor handle structure
typedef struct {
    uart_port_t uart_port;
    tb600b_sensor_type_t sensor_type;
} tb600b_handle_t;

/**
 * @brief Initialize TB600B sensor handle
 * 
 * @param handle Pointer to sensor handle
 * @param port UART port number
 * @param sensor_type Type of sensor (VOC/TEMP/HUMID or CO only)
 * 
 * @return 
 *     - ESP_OK: Success
 *     - ESP_FAIL: Invalid parameters
 */
esp_err_t tb600_init(tb600b_handle_t *handle, uart_port_t port, tb600b_sensor_type_t sensor_type);

/**
 * @brief Read VOC/air quality from TB600B sensor
 * 
 * Only works with TB600B_TYPE_VOC_TEMP_HUMID sensor
 * 
 * @param handle Sensor handle
 * @param out_val Pointer to store VOC value (in ppm)
 * 
 * @return 
 *     - ESP_OK: Success
 *     - ESP_FAIL: Communication error
 *     - ESP_ERR_INVALID_CRC: CRC validation failed
 *     - ESP_ERR_INVALID_ARG: Wrong sensor type
 */
esp_err_t tb600_read_voc(tb600b_handle_t *handle, float *out_val);

/**
 * @brief Read CO concentration from TB600B sensor
 * 
 * Works with both sensor types
 * 
 * @param handle Sensor handle
 * @param out_val Pointer to store CO value (in ppm)
 * 
 * @return 
 *     - ESP_OK: Success
 *     - ESP_FAIL: Communication error
 *     - ESP_ERR_INVALID_CRC: CRC validation failed
 */
esp_err_t tb600_read_co(tb600b_handle_t *handle, float *out_val);

/**
 * @brief Read temperature from TB600B sensor
 * 
 * Only works with TB600B_TYPE_VOC_TEMP_HUMID sensor
 * 
 * @param handle Sensor handle
 * @param out_val Pointer to store temperature value (in °C)
 * 
 * @return 
 *     - ESP_OK: Success
 *     - ESP_FAIL: Communication error
 *     - ESP_ERR_INVALID_CRC: CRC validation failed
 *     - ESP_ERR_INVALID_ARG: Wrong sensor type
 */
esp_err_t tb600_read_temp(tb600b_handle_t *handle, float *out_val);

/**
 * @brief Read humidity from TB600B sensor
 * 
 * Only works with TB600B_TYPE_VOC_TEMP_HUMID sensor
 * 
 * @param handle Sensor handle
 * @param out_val Pointer to store humidity value (in %)
 * 
 * @return 
 *     - ESP_OK: Success
 *     - ESP_FAIL: Communication error
 *     - ESP_ERR_INVALID_CRC: CRC validation failed
 *     - ESP_ERR_INVALID_ARG: Wrong sensor type
 */
esp_err_t tb600_read_humidity(tb600b_handle_t *handle, float *out_val);

/**
 * @brief Read all values (VOC, temperature, and humidity) from TB600B sensor
 * 
 * Only works with TB600B_TYPE_VOC_TEMP_HUMID sensor
 * 
 * @param handle Sensor handle
 * @param voc_val Pointer to store VOC value (in ppm)
 * @param temp_val Pointer to store temperature value (in °C)
 * @param humid_val Pointer to store humidity value (in %)
 * 
 * @return 
 *     - ESP_OK: Success
 *     - ESP_FAIL: Communication error
 *     - ESP_ERR_INVALID_CRC: CRC validation failed
 *     - ESP_ERR_INVALID_ARG: Wrong sensor type
 */
esp_err_t tb600_read_all(tb600b_handle_t *handle, float *voc_val, float *temp_val, float *humid_val);

/**
 * @brief Get sensor type as string for logging
 * 
 * @param handle Sensor handle
 * 
 * @return String describing sensor type
 */
const char* tb600_get_sensor_type_str(tb600b_handle_t *handle);

#ifdef __cplusplus
}
#endif

#endif // TB600B_H