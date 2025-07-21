#!/opt/wlanpi-core/bin/python3

import argparse
import logging
import sys

from wlanpi_core.services.network_namespace_service import NetworkNamespaceService
from wlanpi_core.schemas.network.network import NetConfig

logging.basicConfig(level=logging.INFO)

def main():
    parser = argparse.ArgumentParser(description="Network Service")
    parser.add_argument("--namespace", required=True, help="Namespace to use")
    parser.add_argument("--ssid", required=True, help="SSID")
    parser.add_argument("--psk", required=True, help="PSK")
    parser.add_argument("--iface", default="wlan0", help="Interface to use")
    parser.add_argument("--set-default-route", action="store_true", help="Set default route")

    args = parser.parse_args()

    svc = NetworkNamespaceService()
    config = NetConfig(id="test", namespace=args.namespace, phy="phy0", security="WPA2-PSK", interface=args.iface, ssid=args.ssid, psk=args.psk)

    try:
        svc.restore_phy_to_userspace(args.namespace)
        status = svc.add_network(
            iface=args.iface,
            net_config=config,
            namespace=args.namespace,
            set_default_route=args.set_default_route
        )
        print(f"Connected: {status}")
    except Exception as e:
        logging.exception("Failed to connect")
        sys.exit(1)

if __name__ == "__main__":
    exit(main())