# Sample flow CSVs

Run `python scripts/make_sample_csvs.py` to (re)generate 10 CSVs here, each a real held-out
CIC-IDS2017 window with the full feature set in raw units. Upload any of them on the **Classify** tab.

| File | Contents |
|---|---|
| 01_benign_traffic.csv | normal traffic only |
| 02_dos_attack.csv | a DoS window |
| 03_portscan_attack.csv | a port scan |
| 04_ddos_attack.csv | a DDoS flood |
| 05_bruteforce_attack.csv | brute force |
| 06_infiltration_attack.csv | infiltration |
| 07_botnet_attack.csv | botnet |
| 08_webattack_attack.csv | web attack |
| 09_mixed_attacks.csv | several attacks mixed |
| 10_nmap_scan_live.csv | a real nmap scan captured in the cyber range |
