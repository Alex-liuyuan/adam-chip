#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "soc_product.h"

void host_uart_ready(uint8_t value);
uint8_t host_uart_value(void);
void host_dma_mode(uint32_t value);

int main(void)
{
    assert(soc_product_capabilities() == 15U);
    host_uart_ready(1U);
    assert(soc_product_uart_smoke() == 0 && host_uart_value() == 'P');
    host_dma_mode(1U);
    assert(soc_product_dma_smoke() == 0);
    assert(soc_product_ai_smoke() == 0);
    puts("MICROPYTHON_API_PASS UART_APP_PASS DMA_APP_PASS AI_APP_PASS RVV_INFERENCE_PASS");
    return 0;
}
