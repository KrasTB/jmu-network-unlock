/* MinGW/Windows compat: <syslog.h> stub (no syslog on Windows). */
#ifndef JMU_COMPAT_SYSLOG_H
#define JMU_COMPAT_SYSLOG_H

#define LOG_EMERG 0
#define LOG_ALERT 1
#define LOG_CRIT 2
#define LOG_ERR 3
#define LOG_WARNING 4
#define LOG_NOTICE 5
#define LOG_INFO 6
#define LOG_DEBUG 7

#define LOG_PID 0x01
#define LOG_CONS 0x02
#define LOG_NDELAY 0x08

#define openlog(ident, option, facility) ((void)0)
#define closelog() ((void)0)
#define syslog(priority, fmt, ...) ((void)0)

#endif
