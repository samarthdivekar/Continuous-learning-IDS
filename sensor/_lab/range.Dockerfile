FROM alpine:3.20
# nmap: the attacker's port scan (reconnaissance only). tcpdump: each host's own capture (its "sensor").
# busybox-extras: httpd and nc, the services the hosts offer and the normal traffic the workstations make.
RUN apk add --no-cache nmap tcpdump busybox-extras
