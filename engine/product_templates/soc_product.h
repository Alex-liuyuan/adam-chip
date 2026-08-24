#ifndef SOC_PRODUCT_H
#define SOC_PRODUCT_H
#include <stdint.h>
uint32_t soc_product_capabilities(void);
int soc_product_uart_smoke(void);
int soc_product_dma_smoke(void);
int soc_product_ai_smoke(void);
#endif
