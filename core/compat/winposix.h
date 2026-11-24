/* Force-included POSIX shim for building jmuSupplicant with MinGW-w64.
 * Provides the handful of POSIX-isms the source uses: u_int*_t, struct flock
 * + fcntl file locks, sigaction/alarm, daemon(), open() wrappers.
 * None of these actually do anything useful on Windows; the program only
 * needs them to compile and run in the foreground.
 */
#ifndef JMU_WINPOSIX_H
#define JMU_WINPOSIX_H

#include <winsock2.h>
#include <ws2tcpip.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <io.h>
#include <fcntl.h>
#include <sys/types.h>

typedef uint8_t u_int8_t;
typedef uint16_t u_int16_t;
typedef uint32_t u_int32_t;
typedef uint64_t u_int64_t;

/* open()/_open() */
#define open _open
#define close _close
#define read _read
#define write _write
#ifndef O_CREAT
#define O_CREAT _O_CREAT
#endif
#ifndef O_RDWR
#define O_RDWR _O_RDWR
#endif

/* fcntl advisory locks: no-ops */
#ifndef F_RDLCK
#define F_RDLCK 0
#endif
#ifndef F_WRLCK
#define F_WRLCK 1
#endif
#ifndef F_UNLCK
#define F_UNLCK 2
#endif
#ifndef F_GETLK
#define F_GETLK 5
#endif
#ifndef F_SETLK
#define F_SETLK 6
#endif
#ifndef F_SETLKW
#define F_SETLKW 7
#endif

struct flock {
  short l_type;
  short l_whence;
  off_t l_start;
  off_t l_len;
  pid_t l_pid;
};

static __inline int fcntl_win_stub(int fd, int cmd, ...)
{
  (void)fd;
  (void)cmd;
  return 0;
}
#define fcntl(fd, cmd, ...) fcntl_win_stub((fd), (cmd))

/* signals: single-threaded polling instead of SIGALRM */
#ifndef SIGALRM
#define SIGALRM 14
#endif
#ifndef SIGUSR1
#define SIGUSR1 10
#endif

#if !defined(_JMU_SIGINFO_TYPEDEF)
#define _JMU_SIGINFO_TYPEDEF
typedef struct { int si_signo; int si_errno; int si_code; } siginfo_t;
#endif

struct sigaction {
  void (*sa_handler)(int, siginfo_t *, void *);
  int sa_mask;
  int sa_flags;
};

static __inline int sigfillset_stub(void *set) { (void)set; return 0; }
static __inline int sigemptyset_stub(void *set) { (void)set; return 0; }
static __inline int sigaction_stub(int sig, const struct sigaction *act, struct sigaction *old)
{
  (void)sig; (void)act; (void)old;
  return 0;
}
#define sigfillset(set) sigfillset_stub((set))
#define sigemptyset(set) sigemptyset_stub((set))
#define sigaction(sig, act, old) sigaction_stub((sig), (act), (old))

static __inline unsigned int alarm_stub(unsigned int seconds)
{
  (void)seconds;
  return 0;
}
#define alarm(sec) alarm_stub((unsigned int)(sec))

#ifndef SIGKILL
#define SIGKILL 9
#endif
static __inline int kill_stub(int pid, int sig)
{
  (void)pid; (void)sig;
  return 0;
}
#define kill(pid, sig) kill_stub((pid), (sig))

static __inline int daemon_stub(int nochdir, int noclose)
{
  (void)nochdir; (void)noclose;
  return 0;
}
#define daemon(a, b) daemon_stub((a), (b))

/* ethernet header (MinGW has no <net/ethernet.h>) */
#ifndef ETHER_ADDR_LEN
#define ETHER_ADDR_LEN 6
#endif
#ifndef JMU_ETHER_HEADER_DEFINED
#define JMU_ETHER_HEADER_DEFINED
struct ether_header {
  unsigned char ether_dhost[ETHER_ADDR_LEN];
  unsigned char ether_shost[ETHER_ADDR_LEN];
  uint16_t ether_type;
};
#endif /* JMU_ETHER_HEADER_DEFINED */

#endif /* JMU_WINPOSIX_H */
