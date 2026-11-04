/* mmap / munmap para compilar el modulo de animaciones en Windows (MinGW): solo lo que usa, memoria anonima de
   lectura y escritura debajo de los 4 GB (MAP_32BIT), con VirtualAlloc buscando una direccion baja libre. */
#ifndef RE4N95_SYS_MMAN_H
#define RE4N95_SYS_MMAN_H
#include <windows.h>
#include <stddef.h>
#include <stdint.h>

#define PROT_READ 1
#define PROT_WRITE 2
#define MAP_PRIVATE 2
#define MAP_ANONYMOUS 0x20
#define MAP_32BIT 0x40
#define MAP_FAILED ((void*) -1)

static inline void* mmap(void* addr, size_t len, int prot, int flags, int fd, long off) {
    (void) addr; (void) prot; (void) flags; (void) fd; (void) off;
    for (uintptr_t a = 0x10000000u; a + len < 0xFFFF0000u; a += 0x100000u) {
        void* p = VirtualAlloc((void*) a, len, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
        if (p) return p;
    }
    return MAP_FAILED;
}

static inline int munmap(void* p, size_t len) {
    (void) len;
    return VirtualFree(p, 0, MEM_RELEASE) ? 0 : -1;
}
#endif
