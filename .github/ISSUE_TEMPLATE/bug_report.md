---
name: Bug report
about: Create a report to help us fix a wlanpi-core bug.
title: ''
labels: ''
assignees: ''

---

**Describe the bug**

Description of the issue.

**To Reproduce**

Steps to reproduce the issue.

**Expected behavior**

What you expected to happen.

**Debug output**

We are in the process of improving our logging in wlanpi-core. Reproduce the issue and gather the following output.

```
tail gunicorn_error.log
tail nginx_error.log
systemctl status wlanpi-core
journalctl -u wlanpi-core -b -r
```

**Software and hardware(please complete the following information):**

 - OS and version: [e.g. WLAN Pi OS `lsb_release -a` and `sudo cat /etc/wlanpi-release`]
 - Kernel version: [e.g. `uname -a`]
 - Hardware: [e.g. RBPi 4, WLAN Pi Pro, WLAN Pi M4, provide details from `wlanpi-model`]
 - Package version: [e.g. get from `dpkg -l wlanpi-core`]