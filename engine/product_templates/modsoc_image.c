#include "py/runtime.h"
#include "soc_product.h"

STATIC mp_obj_t product_capabilities(void)
{
    return mp_obj_new_int_from_uint(soc_product_capabilities());
}
MP_DEFINE_CONST_FUN_OBJ_0(product_capabilities_obj, product_capabilities);

STATIC mp_obj_t product_uart_smoke(void)
{
    return mp_obj_new_bool(soc_product_uart_smoke() == 0);
}
MP_DEFINE_CONST_FUN_OBJ_0(product_uart_smoke_obj, product_uart_smoke);

STATIC mp_obj_t product_dma_smoke(void)
{
    return mp_obj_new_bool(soc_product_dma_smoke() == 0);
}
MP_DEFINE_CONST_FUN_OBJ_0(product_dma_smoke_obj, product_dma_smoke);

STATIC mp_obj_t product_ai_smoke(void)
{
    return mp_obj_new_bool(soc_product_ai_smoke() == 0);
}
MP_DEFINE_CONST_FUN_OBJ_0(product_ai_smoke_obj, product_ai_smoke);

STATIC const mp_rom_map_elem_t soc_image_globals_table[] = {
    {MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_soc_image)},
    {MP_ROM_QSTR(MP_QSTR_capabilities), MP_ROM_PTR(&product_capabilities_obj)},
    {MP_ROM_QSTR(MP_QSTR_uart_smoke), MP_ROM_PTR(&product_uart_smoke_obj)},
    {MP_ROM_QSTR(MP_QSTR_dma_smoke), MP_ROM_PTR(&product_dma_smoke_obj)},
    {MP_ROM_QSTR(MP_QSTR_ai_smoke), MP_ROM_PTR(&product_ai_smoke_obj)},
};
STATIC MP_DEFINE_CONST_DICT(soc_image_globals, soc_image_globals_table);

const mp_obj_module_t mp_module_soc_image = {
    .base = {&mp_type_module},
    .globals = (mp_obj_dict_t *)&soc_image_globals,
};
