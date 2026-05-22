#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#include <stdbool.h>
#include "esp_err.h"

// =====================================================
// WIFI API
// =====================================================

/**
 * @brief Initialize WiFi in Station mode
 *
 * Features:
 * - Auto reconnect
 * - Event handling
 * - ESP-IDF v5.x compatible
 * - Stable for ESP-NOW + MQTT + SNTP
 */
void wifi_init_sta(void);

/**
 * @brief Check WiFi connection state
 *
 * @return true  Connected
 * @return false Not connected
 */
bool wifi_is_connected(void);

#ifdef __cplusplus
}
#endif