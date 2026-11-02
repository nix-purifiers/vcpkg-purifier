#include <stdio.h>
#include <string.h>
#include <zlib.h>
int main(void) {
    puts(zlibVersion());
    return strcmp(zlibVersion(), "1.3.2") != 0;
}
