/* Added 2026-11-24: report only fixed status tokens, never account or packet data.
 * Distributed with the combined core under GPL-3.0-or-later.
 */
#include "auth_status.h"
#include <stdio.h>
#include <string.h>
#if defined(_WIN32)
#include <windows.h>
#include <wchar.h>
#endif

void report_auth_status(const char *status)
{
#if defined(_WIN32)
    wchar_t path[32768], temporary[32768];
    DWORD length;
    FILE *stream;
    if (strcmp(status, "SUCCESS") && strcmp(status, "STAGE1_OK") &&
        strcmp(status, "RETRYING") && strcmp(status, "FAILURE")) return;
    length = GetEnvironmentVariableW(L"JMU_AUTH_RESULT_FILE", path, 32768);
    if (!length || length >= 32760) return;
    wcscpy(temporary, path);
    wcscat(temporary, L".tmp");
    stream = _wfopen(temporary, L"wb");
    if (!stream) return;
    fputs(status, stream);
    fputs("\n", stream);
    if (fclose(stream) != 0) { DeleteFileW(temporary); return; }
    if (!MoveFileExW(temporary, path, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
        DeleteFileW(temporary);
#else
    (void)status;
#endif
}
