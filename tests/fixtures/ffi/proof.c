#include <zlib.h>
int answer(void) { return zlibVersion()[0] == '1' ? 42 : 0; }
