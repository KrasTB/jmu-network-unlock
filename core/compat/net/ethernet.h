/* MinGW/Windows compat: BSD <net/ethernet.h>. */
#ifndef JMU_COMPAT_NET_ETHERNET_H
#define JMU_COMPAT_NET_ETHERNET_H

#include <stdint.h>

#define ETHER_ADDR_LEN 6
#define ETHER_TYPE_LEN 2
#define ETHER_CRC_LEN 4
#define ETHER_HDR_LEN 14
#define ETHER_MIN_LEN 64

struct ether_addr {
  unsigned char ether_addr_octet[ETHER_ADDR_LEN];
};

#ifndef JMU_ETHER_HEADER_DEFINED
#define JMU_ETHER_HEADER_DEFINED
struct ether_header {
  unsigned char ether_dhost[ETHER_ADDR_LEN];
  unsigned char ether_shost[ETHER_ADDR_LEN];
  uint16_t ether_type;
};
#endif

#endif
