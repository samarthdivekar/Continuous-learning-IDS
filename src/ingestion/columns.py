"""Column-name normalisation across CIC-IDS2017 / CSE-CIC-IDS2018 releases.

The error-corrected releases use one header; the original CIC releases use
several abbreviated variants (e.g. "Tot Fwd Pkts" vs "Total Fwd Packet").
Everything is mapped to a canonical snake_case name so downstream code never
sees dataset-specific spellings.
"""
from __future__ import annotations

import re

# Canonical identifiers (never used as edge features).
ID_COLUMNS = {"id", "flow_id", "src_ip", "src_port", "dst_ip", "timestamp", "label", "attempted_category"}

# Known alternate spellings -> canonical name. Keys are compared after
# `_basic_snake` so casing/punctuation variations are handled automatically.
ALIASES = {
    "source_ip": "src_ip",
    "destination_ip": "dst_ip",
    "source_port": "src_port",
    "destination_port": "dst_port",
    "tot_fwd_pkts": "total_fwd_packet",
    "total_fwd_packets": "total_fwd_packet",
    "tot_bwd_pkts": "total_bwd_packets",
    "totlen_fwd_pkts": "total_length_of_fwd_packet",
    "total_length_of_fwd_packets": "total_length_of_fwd_packet",
    "totlen_bwd_pkts": "total_length_of_bwd_packet",
    "total_length_of_bwd_packets": "total_length_of_bwd_packet",
    "fwd_pkt_len_max": "fwd_packet_length_max",
    "fwd_pkt_len_min": "fwd_packet_length_min",
    "fwd_pkt_len_mean": "fwd_packet_length_mean",
    "fwd_pkt_len_std": "fwd_packet_length_std",
    "bwd_pkt_len_max": "bwd_packet_length_max",
    "bwd_pkt_len_min": "bwd_packet_length_min",
    "bwd_pkt_len_mean": "bwd_packet_length_mean",
    "bwd_pkt_len_std": "bwd_packet_length_std",
    "flow_byts_s": "flow_bytes_per_s",
    "flow_pkts_s": "flow_packets_per_s",
    "fwd_pkts_s": "fwd_packets_per_s",
    "bwd_pkts_s": "bwd_packets_per_s",
    "fwd_header_len": "fwd_header_length",
    "bwd_header_len": "bwd_header_length",
    "pkt_len_min": "packet_length_min",
    "min_packet_length": "packet_length_min",
    "pkt_len_max": "packet_length_max",
    "max_packet_length": "packet_length_max",
    "pkt_len_mean": "packet_length_mean",
    "pkt_len_std": "packet_length_std",
    "pkt_len_var": "packet_length_variance",
    "fin_flag_cnt": "fin_flag_count",
    "syn_flag_cnt": "syn_flag_count",
    "rst_flag_cnt": "rst_flag_count",
    "psh_flag_cnt": "psh_flag_count",
    "ack_flag_cnt": "ack_flag_count",
    "urg_flag_cnt": "urg_flag_count",
    "cwe_flag_count": "cwr_flag_count",
    "ece_flag_cnt": "ece_flag_count",
    "pkt_size_avg": "average_packet_size",
    "fwd_seg_size_avg": "fwd_segment_size_avg",
    "avg_fwd_segment_size": "fwd_segment_size_avg",
    "bwd_seg_size_avg": "bwd_segment_size_avg",
    "avg_bwd_segment_size": "bwd_segment_size_avg",
    "subflow_fwd_pkts": "subflow_fwd_packets",
    "subflow_fwd_byts": "subflow_fwd_bytes",
    "subflow_bwd_pkts": "subflow_bwd_packets",
    "subflow_bwd_byts": "subflow_bwd_bytes",
    "init_fwd_win_byts": "fwd_init_win_bytes",
    "init_win_bytes_forward": "fwd_init_win_bytes",
    "init_bwd_win_byts": "bwd_init_win_bytes",
    "init_win_bytes_backward": "bwd_init_win_bytes",
    "fwd_act_data_pkts": "fwd_act_data_pkts",
    "act_data_pkt_fwd": "fwd_act_data_pkts",
    "fwd_seg_size_min": "fwd_seg_size_min",
    "min_seg_size_forward": "fwd_seg_size_min",
}


def _basic_snake(name: str) -> str:
    s = name.strip().lower().replace("/", "_per_")
    s = re.sub(r"[^0-9a-z]+", "_", s)
    return s.strip("_")


def canonical_name(name: str) -> str:
    s = _basic_snake(name)
    return ALIASES.get(s, s)


def normalise_columns(columns: list[str]) -> dict[str, str]:
    """Return {original: canonical}. Raises if two columns collapse to one name."""
    mapping, seen = {}, {}
    for c in columns:
        can = canonical_name(c)
        if can in seen:
            raise ValueError(f"Columns {seen[can]!r} and {c!r} both normalise to {can!r}")
        seen[can] = c
        mapping[c] = can
    return mapping
