# The flow meter the live sensor uses: GintsEngelen/CICFlowMeter, the corrected CICFlowMeter that produced
# the improved CIC-IDS2017 / CSE-CIC-IDS2018 releases this project trains on. It is pinned to e3bb9ce
# (25 July 2022), the last commit before features the training data does not have (TCP retransmission
# counts, "Total Connection Flow Time", backward segment features). Its CSV header must equal the
# training data's; the sensor checks that on every capture.
#
#   docker build -t gnnids-cicflowmeter -f sensor/cicflowmeter.Dockerfile sensor
#   docker run --rm -v <dir>:/data gnnids-cicflowmeter /data/in /data/out

# Ubuntu (glibc), not Alpine: the bundled libjnetpcap.so is a glibc build and fails to load on musl.
FROM eclipse-temurin:8-jdk-jammy AS builder
RUN apt-get update && apt-get install -y --no-install-recommends git libpcap-dev && rm -rf /var/lib/apt/lists/*
ARG COMMIT=e3bb9ce18d349ffb274d3bea05bf80f37eabec46
RUN git clone https://github.com/GintsEngelen/CICFlowMeter.git /CICFlowMeter \
 && cd /CICFlowMeter && git checkout --quiet "$COMMIT"
WORKDIR /CICFlowMeter
# installDist lays out the distribution tree (bin/cfm, lib/, lib/native) without building the zip,
# whose duplicate entries Ubuntu's unzip rejects as a possible zip bomb
RUN ./gradlew --no-daemon installDist

FROM eclipse-temurin:8-jre-jammy
RUN apt-get update && apt-get install -y --no-install-recommends libpcap0.8 && rm -rf /var/lib/apt/lists/* \
 && ln -sf /usr/lib/x86_64-linux-gnu/libpcap.so.0.8 /usr/lib/x86_64-linux-gnu/libpcap.so
COPY --from=builder /CICFlowMeter/build/install/CICFlowMeter /CICFlowMeter
# cfm resolves -Djava.library.path=../lib/native relative to bin/
WORKDIR /CICFlowMeter/bin
ENTRYPOINT ["./cfm"]
