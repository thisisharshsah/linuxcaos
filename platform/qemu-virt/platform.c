/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <stdint.h>
#include "platform.h"

/* QEMU virt PL011 only. These addresses do NOT describe Apple hardware. */
#define UART_BASE 0x09000000UL
#define UART_DR (*(volatile uint32_t *)(UART_BASE + 0x00))
#define UART_FR (*(volatile uint32_t *)(UART_BASE + 0x18))
#define UART_LCRH (*(volatile uint32_t *)(UART_BASE + 0x2c))
#define UART_CR (*(volatile uint32_t *)(UART_BASE + 0x30))
#define FR_RXFE (1U << 4)
#define FR_TXFF (1U << 5)

void platform_console_init(void) {
    UART_CR = 0;
    UART_LCRH = 3U << 5; /* 8-bit words, FIFO disabled */
    UART_CR = (1U << 9) | (1U << 8) | 1U;
}

void platform_console_putc(char c) {
    while (UART_FR & FR_TXFF) {}
    UART_DR = (uint32_t)(unsigned char)c;
}

char platform_console_getc(void) {
    while (UART_FR & FR_RXFE) {}
    return (char)(UART_DR & 0xffU);
}

const char *platform_name(void) {
    return "QEMU virt";
}
