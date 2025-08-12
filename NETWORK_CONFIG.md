# Network Config

This is documentation on how to use the Network Config system, and control namespaces as well as running apps inside of them.

## Setting Up App List

To be able to run apps in the namespaces, there is a JSON file that declares all the apps that can be run, with their respective command. This is to stop the user from running anything they want through the API.

To configure which apps can be run in namespaces, edit the JSON file at `/etc/wifictl/apps.json`. This file lists the allowed apps and their commands.

For example, to allow running `orb` from a namespace, your `apps.json` should look like:

```json
{
    "orb": "/usr/bin/orb sensor"
}
```

Use the key (e.g. `"orb"`) when referencing the app in your network config.


## Creating Configs

New configs are created through the API, found at the docs page `http://[wlanpi-address]:31415/docs`, under the network config section

There will be base json provided when using the API through the docs, and you can fill in the required fields. 

The full schema:

```
id:                 id/name of the config
namespace:          the name of the namespace to run it in
use_namespace:      if the namespace should be used or not (defaults to False)
mode:               either "managed" or "monitor"
iface_display_name: name of the interface for the scanning api to use (e.g. wlanpi<x> or myiface<x>)
phy:                the phy to use (defaults to phy0)
interface:          the interface to use (defaults to wlan0)
security ↓
    ssid:           SSID of the network
    security:       security standard to use, e.g. "WPA2-PSK"
    psk:            password of the network (optional)
    identity:       optional
    password:       optional
    client_cert:    optional
    private_key:    optional
    ca_cert:        optional
mlo:                whether to use mlo or not (optional, default False)
default_route:      whether to set this namespace as the default route (default False)
autostart_app:      name of the app defined in the apps list above (optional)
```

Here is an example config that connects to a WPA2 network and runs orb:
```json
{
  "id": "mycfg",
  "namespace": "myns",
  "use_namespace": true,
  "mode": "managed",
  "iface_display_name": "myiface",
  "phy": "phy0",
  "interface": "wlan0",
  "security": {
    "ssid": "SSID",
    "security": "WPA2-PSK",
    "psk": "PSK"
  },
  "mlo": false,
  "default_route": false,
  "autostart_app": "orb",
}
```

## Using Configs

There are 2 API endpoints for interacting with the configs, `/api/v1/network/config/activate/{id}` and `/api/v1/network/config/deactivate/{id}`.

The Active endpoint will move the interface specified into the namespace, connect to the network and start the app (if specified). 

For deactivating, it does the steps in reverse, stopping the app, and restoring the interface back to how it was (the root namespace). A config must be active to deactivate it, however you can override this by setting `override_active` to true, useful if something has broken and needs to be reset.

Please bear in mind that the namespaces do not persist on reboot. 

To combat this, once a config is started, the ID gets written to a file, so that on reboot it will automatically activate that config.


## Managing Configs

Configs can be updated using the endpoint `/api/v1/network/config/{id}` with method PATCH.
You should only include fields that you want to update when filling in the JSON, and a config must be deactivated to modify it.

Configs can be deleted using the endpoint `/api/v1/network/config/{id}` with method DELETE.
A config must be deactivated to delete it, however you can set the `force` paramater to true to delete it anyway.


## Network Status

The endpoint `/api/v1/network/config/status` will output an overview of all the namespaces (including root), and in them, the interfaces and their details.

This is what an example output would look like:
```json
{
  "root": {
    "wlanpi1": {
      "ifindex": "6",
      "wdev": "0x100000002",
      "addr_9c": "xx:xx:xx:xx:xx",
      "type": "monitor",
      "channel": "1 (2412 MHz), width: 20 MHz (no HT), center1: 2412 MHz"
    },
    "wlan1": {
      "ifindex": "5",
      "wdev": "0x100000001",
      "addr_9c": "xx:xx:xx:xx:xx",
      "type": "managed"
    }
  },
  "testns": {
    "wlan0": {
      "ifindex": "30",
      "wdev": "0x4f",
      "addr_e8": "xx:xx:xx:xx:xx",
      "ssid": "SSID",
      "type": "managed",
      "channel": "149 (5745 MHz), width: 80 MHz, center1: 5775 MHz",
      "txpower": "22.00 dBm"
    },
    "wlanpi0": {
      "ifindex": "7",
      "wdev": "0x2",
      "addr_e8": "xx:xx:xx:xx:xx",
      "type": "monitor"
    }
  }
}
```

