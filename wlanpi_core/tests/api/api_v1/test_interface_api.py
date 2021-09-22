import pytest

from wlanpi_core.services.interface_service import (
    get_center_channel_frequencies,
    parse_iw_dev,
)

iw_dev_output_a = """
phy#0
        Unnamed/non-netdev interface
                wdev 0x2
                addr 70:cf:49:ff:ff:ff
                type P2P-device
                txpower 0.00 dBm
        Interface wlan0
                ifindex 4
                wdev 0x1
                addr 70:cf:49:ff:ff:ff
                type managed
                txpower 0.00 dBm
                multicast TXQ:
                        qsz-byt qsz-pkt flows   drops   marks   overlmt hashcol tx-bytes        tx-packets
                        0       0       0       0       0       0       0       0               0
"""

iw_dev_output_b = """
phy#3
        Interface wlan1
                ifindex 7
                wdev 0x300000001
                addr 8c:88:2a:ff:ff:ff
                type monitor
                channel 10 (2457 MHz), width: 20 MHz (no HT), center1: 2457 MHz
                txpower 21.00 dBm
                multicast TXQ:
                        qsz-byt qsz-pkt flows   drops   marks   overlmt hashcol tx-bytes        tx-packets
                        0       0       0       0       0       0       0       0               0
phy#2
        Interface wlan2
                ifindex 5
                wdev 0x200000001
                addr 8c:88:2b:ff:ff:ff
                type managed
                txpower 21.00 dBm
                multicast TXQ:
                        qsz-byt qsz-pkt flows   drops   marks   overlmt hashcol tx-bytes        tx-packets
                        0       0       0       0       0       0       0       0               0
phy#1
        Interface wlan0
                ifindex 3
                wdev 0x100000001
                addr dc:a6:32:ff:ff:ff
                type managed
                channel 34 (5170 MHz), width: 20 MHz, center1: 5170 MHz
"""

channel_output_a = """
Band 1:
        * 2412 MHz [1]
          Maximum TX power: 22.0 dBm
          Channel widths: 20MHz HT40+
        * 2417 MHz [2]
          Maximum TX power: 22.0 dBm
          Channel widths: 20MHz HT40+
        * 2422 MHz [3]
          Maximum TX power: 22.0 dBm
          Channel widths: 20MHz HT40+
        * 2427 MHz [4]
          Maximum TX power: 22.0 dBm
          Channel widths: 20MHz HT40+
        * 2432 MHz [5]
          Maximum TX power: 22.0 dBm
          Channel widths: 20MHz HT40- HT40+
        * 2437 MHz [6]
          Maximum TX power: 22.0 dBm
          Channel widths: 20MHz HT40- HT40+
        * 2442 MHz [7]
          Maximum TX power: 22.0 dBm
          Channel widths: 20MHz HT40- HT40+
        * 2447 MHz [8]
          Maximum TX power: 22.0 dBm
          Channel widths: 20MHz HT40- HT40+
        * 2452 MHz [9]
          Maximum TX power: 22.0 dBm
          Channel widths: 20MHz HT40- HT40+
        * 2457 MHz [10]
          Maximum TX power: 22.0 dBm
          Channel widths: 20MHz HT40-
        * 2462 MHz [11]
          Maximum TX power: 22.0 dBm
          Channel widths: 20MHz HT40-
        * 2467 MHz [12]
          Maximum TX power: 22.0 dBm
          Channel widths: 20MHz HT40-
        * 2472 MHz [13]
          Maximum TX power: 22.0 dBm
          Channel widths: 20MHz HT40-
        * 2484 MHz [14] (disabled)
Band 2:
        * 5180 MHz [36]
          Maximum TX power: 22.0 dBm
          Channel widths: 20MHz HT40+ VHT80 VHT160
        * 5200 MHz [40]
          Maximum TX power: 22.0 dBm
          Channel widths: 20MHz HT40- VHT80 VHT160
        * 5220 MHz [44]
          Maximum TX power: 22.0 dBm
          Channel widths: 20MHz HT40+ VHT80 VHT160
        * 5240 MHz [48]
          Maximum TX power: 22.0 dBm
          Channel widths: 20MHz HT40- VHT80 VHT160
        * 5260 MHz [52]
          Maximum TX power: 22.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40+ VHT80 VHT160
          DFS state: usable (for 3497 sec)
          DFS CAC time: 60000 ms
        * 5280 MHz [56]
          Maximum TX power: 22.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40- VHT80 VHT160
          DFS state: usable (for 3497 sec)
          DFS CAC time: 60000 ms
        * 5300 MHz [60]
          Maximum TX power: 22.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40+ VHT80 VHT160
          DFS state: usable (for 3497 sec)
          DFS CAC time: 60000 ms
        * 5320 MHz [64]
          Maximum TX power: 22.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40- VHT80 VHT160
          DFS state: usable (for 3497 sec)
          DFS CAC time: 60000 ms
        * 5340 MHz [68] (disabled)
        * 5360 MHz [72] (disabled)
        * 5380 MHz [76] (disabled)
        * 5400 MHz [80] (disabled)
        * 5420 MHz [84] (disabled)
        * 5440 MHz [88] (disabled)
        * 5460 MHz [92] (disabled)
        * 5480 MHz [96] (disabled)
        * 5500 MHz [100]
          Maximum TX power: 22.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40+ VHT80 VHT160
          DFS state: usable (for 3497 sec)
          DFS CAC time: 60000 ms
        * 5520 MHz [104]
          Maximum TX power: 22.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40- VHT80 VHT160
          DFS state: usable (for 3497 sec)
          DFS CAC time: 60000 ms
        * 5540 MHz [108]
          Maximum TX power: 22.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40+ VHT80 VHT160
          DFS state: usable (for 3497 sec)
          DFS CAC time: 60000 ms
        * 5560 MHz [112]
          Maximum TX power: 22.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40- VHT80 VHT160
          DFS state: usable (for 3497 sec)
          DFS CAC time: 60000 ms
        * 5580 MHz [116]
          Maximum TX power: 22.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40+ VHT80 VHT160
          DFS state: usable (for 3497 sec)
          DFS CAC time: 60000 ms
        * 5600 MHz [120]
          Maximum TX power: 22.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40- VHT80 VHT160
          DFS state: usable (for 3497 sec)
          DFS CAC time: 60000 ms
        * 5620 MHz [124]
          Maximum TX power: 22.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40+ VHT80 VHT160
          DFS state: usable (for 3497 sec)
          DFS CAC time: 60000 ms
        * 5640 MHz [128]
          Maximum TX power: 22.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40- VHT80 VHT160
          DFS state: usable (for 3497 sec)
          DFS CAC time: 60000 ms
        * 5660 MHz [132]
          Maximum TX power: 22.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40+ VHT80
          DFS state: usable (for 3497 sec)
          DFS CAC time: 60000 ms
        * 5680 MHz [136]
          Maximum TX power: 22.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40- VHT80
          DFS state: usable (for 3497 sec)
          DFS CAC time: 60000 ms
        * 5700 MHz [140]
          Maximum TX power: 22.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40+ VHT80
          DFS state: usable (for 3497 sec)
          DFS CAC time: 60000 ms
        * 5720 MHz [144]
          Maximum TX power: 22.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40- VHT80
          DFS state: usable (for 3497 sec)
          DFS CAC time: 60000 ms
        * 5745 MHz [149]
          Maximum TX power: 22.0 dBm
          Channel widths: 20MHz HT40+ VHT80
        * 5765 MHz [153]
          Maximum TX power: 22.0 dBm
          Channel widths: 20MHz HT40- VHT80
        * 5785 MHz [157]
          Maximum TX power: 22.0 dBm
          Channel widths: 20MHz HT40+ VHT80
        * 5805 MHz [161]
          Maximum TX power: 22.0 dBm
          Channel widths: 20MHz HT40- VHT80
        * 5825 MHz [165]
          Maximum TX power: 22.0 dBm
          Channel widths: 20MHz
        * 5845 MHz [169] (disabled)
        * 5865 MHz [173] (disabled)
        * 5885 MHz [177] (disabled)
        * 5905 MHz [181] (disabled)
Band 4:
        * 5955 MHz [1]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 5975 MHz [5]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 5995 MHz [9]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6015 MHz [13]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6035 MHz [17]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6055 MHz [21]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6075 MHz [25]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6095 MHz [29]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6115 MHz [33]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6135 MHz [37]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6155 MHz [41]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6175 MHz [45]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6195 MHz [49]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6215 MHz [53]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6235 MHz [57]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6255 MHz [61]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6275 MHz [65]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6295 MHz [69]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6315 MHz [73]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6335 MHz [77]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6355 MHz [81]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6375 MHz [85]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6395 MHz [89]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6415 MHz [93]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6435 MHz [97]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6455 MHz [101]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6475 MHz [105]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6495 MHz [109]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6515 MHz [113]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6535 MHz [117]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6555 MHz [121]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6575 MHz [125]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6595 MHz [129]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6615 MHz [133]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6635 MHz [137]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6655 MHz [141]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6675 MHz [145]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6695 MHz [149]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6715 MHz [153]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6735 MHz [157]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6755 MHz [161]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6775 MHz [165]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6795 MHz [169]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6815 MHz [173]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6835 MHz [177]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6855 MHz [181]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6875 MHz [185]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6895 MHz [189]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6915 MHz [193]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6935 MHz [197]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6955 MHz [201]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6975 MHz [205]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 6995 MHz [209]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 7015 MHz [213]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 7035 MHz [217]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 7055 MHz [221]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 7075 MHz [225]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 7095 MHz [229]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
        * 7115 MHz [233]
          Maximum TX power: 22.0 dBm
          No IR
          Channel widths: 20MHz
"""

channel_output_b = """
Band 1:
        * 2412 MHz [1] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40+
        * 2417 MHz [2] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40+
        * 2422 MHz [3] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40+
        * 2427 MHz [4] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40+
        * 2432 MHz [5] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40- HT40+
        * 2437 MHz [6] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40- HT40+
        * 2442 MHz [7] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40- HT40+
        * 2447 MHz [8] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40-
        * 2452 MHz [9] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40-
        * 2457 MHz [10] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40-
        * 2462 MHz [11] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40-
        * 2467 MHz [12] (disabled)
        * 2472 MHz [13] (disabled)
        * 2484 MHz [14] (disabled)
Band 2:
        * 5170 MHz [34] (disabled)
        * 5180 MHz [36] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40+ VHT80
        * 5190 MHz [38] (disabled)
        * 5200 MHz [40] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40- VHT80
        * 5210 MHz [42] (disabled)
        * 5220 MHz [44] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40+ VHT80
        * 5230 MHz [46] (disabled)
        * 5240 MHz [48] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40- VHT80
        * 5260 MHz [52] 
          Maximum TX power: 20.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40+ VHT80
          DFS state: usable (for 140538 sec)
          DFS CAC time: 60000 ms
        * 5280 MHz [56] 
          Maximum TX power: 20.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40- VHT80
          DFS state: usable (for 140538 sec)
          DFS CAC time: 60000 ms
        * 5300 MHz [60] 
          Maximum TX power: 20.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40+ VHT80
          DFS state: usable (for 140538 sec)
          DFS CAC time: 60000 ms
        * 5320 MHz [64] 
          Maximum TX power: 20.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40- VHT80
          DFS state: usable (for 140538 sec)
          DFS CAC time: 60000 ms
        * 5500 MHz [100] 
          Maximum TX power: 20.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40+ VHT80
          DFS state: usable (for 140538 sec)
          DFS CAC time: 60000 ms
        * 5520 MHz [104] 
          Maximum TX power: 20.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40- VHT80
          DFS state: usable (for 140538 sec)
          DFS CAC time: 60000 ms
        * 5540 MHz [108] 
          Maximum TX power: 20.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40+ VHT80
          DFS state: usable (for 140538 sec)
          DFS CAC time: 60000 ms
        * 5560 MHz [112] 
          Maximum TX power: 20.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40- VHT80
          DFS state: usable (for 140538 sec)
          DFS CAC time: 60000 ms
        * 5580 MHz [116] 
          Maximum TX power: 20.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40+ VHT80
          DFS state: usable (for 140538 sec)
          DFS CAC time: 60000 ms
        * 5600 MHz [120] 
          Maximum TX power: 20.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40- VHT80
          DFS state: usable (for 140538 sec)
          DFS CAC time: 60000 ms
        * 5620 MHz [124] 
          Maximum TX power: 20.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40+ VHT80
          DFS state: usable (for 140538 sec)
          DFS CAC time: 60000 ms
        * 5640 MHz [128] 
          Maximum TX power: 20.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40- VHT80
          DFS state: usable (for 140538 sec)
          DFS CAC time: 60000 ms
        * 5660 MHz [132] 
          Maximum TX power: 20.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40+ VHT80
          DFS state: usable (for 140538 sec)
          DFS CAC time: 60000 ms
        * 5680 MHz [136] 
          Maximum TX power: 20.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40- VHT80
          DFS state: usable (for 140538 sec)
          DFS CAC time: 60000 ms
        * 5700 MHz [140] 
          Maximum TX power: 20.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40+ VHT80
          DFS state: usable (for 140538 sec)
          DFS CAC time: 60000 ms
        * 5720 MHz [144] 
          Maximum TX power: 20.0 dBm
          No IR
          Radar detection
          Channel widths: 20MHz HT40- VHT80
          DFS state: usable (for 140538 sec)
          DFS CAC time: 60000 ms
        * 5745 MHz [149] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40+ VHT80
        * 5765 MHz [153] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40- VHT80
        * 5785 MHz [157] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40+ VHT80
        * 5805 MHz [161] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40- VHT80
        * 5825 MHz [165] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz
"""


class TestInterfaceAPI:
    @pytest.mark.parametrize(
        "iw_dev_output,expected",
        [
            (iw_dev_output_a, [("phy0", "wlan0")]),
            (
                iw_dev_output_b,
                [("phy1", "wlan0"), ("phy2", "wlan2"), ("phy3", "wlan1")],
            ),
        ],
    )
    def test_parse_iw_dev(self, iw_dev_output, expected):
        phy_interface_mapping = parse_iw_dev(iw_dev_output)
        for test in expected:
            assert test in phy_interface_mapping

    @pytest.mark.parametrize(
        "channel_output,expected",
        [
            (channel_output_a, 97),
            (channel_output_b, 36),
        ],
    )
    def test_number_get_center_channel_frequencies(self, channel_output, expected):
        channel_mappings = get_center_channel_frequencies(channel_output)
        assert len(channel_mappings) == expected
