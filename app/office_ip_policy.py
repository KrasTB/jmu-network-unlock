"""Documented address exclusions for the shared package only."""
import ipaddress
from package_runtime import data_dir

DEFAULT_OFFICE_IP = '172.20.1.10'
RESERVED_OFFICE_IP = '172.20.1.11'


def check_office_ip(address):
    normalized = str(ipaddress.IPv4Address(address))
    if normalized == RESERVED_OFFICE_IP:
        try:
            personal = (data_dir() / 'personal_office_ip.txt').read_text(encoding='ascii').strip()
        except OSError:
            personal = ''
        if personal != normalized:
            raise ValueError('172.20.1.11 是本分享包的保留地址，请填写其他已确认适用的办公区认证 IP。')
    return normalized
