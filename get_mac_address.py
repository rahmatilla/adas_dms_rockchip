from uuid import getnode as get_mac

mac = get_mac()
mac_str = ':'.join([f'{(mac >> ele) & 0xff:02x}' for ele in range(40, -1, -8)])
print(mac_str)
